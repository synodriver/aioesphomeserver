"""Native API boundary and cancellation regressions from the protocol audit."""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import HelloResponse, PingRequest, PingResponse
from noise.connection import NoiseConnection

from aioesphomeserver import Device, NativeApiServer
from aioesphomeserver.native_api_server import (
    NativeApiConnection,
    NOISE_PROTOCOL_NAME,
    PROTO_TO_MESSAGE_TYPE,
    _varuint_to_bytes,
)


async def _wait_for(predicate: Any) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


class MemoryWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def is_closing(self) -> bool:
        return self.closed

    async def wait_closed(self) -> None:
        pass


@pytest.mark.parametrize("unknown", [False, True], ids=["ping", "unknown"])
def test_client_cannot_skip_hello_with_another_frame(unknown: bool) -> None:
    async def run() -> None:
        device = Device(name="hello-required")
        api = NativeApiServer(name="_api", host="127.0.0.1", port=0)
        device.add_entity(api)
        server_task = asyncio.create_task(api.run())
        writer = None
        try:
            await _wait_for(lambda: api.bound_port is not None)
            assert api.bound_port is not None
            with patch("aioesphomeserver.native_api_server.CLIENT_HELLO_TIMEOUT", 0.02):
                reader, writer = await asyncio.open_connection("127.0.0.1", api.bound_port)
                message_type = 65535 if unknown else PROTO_TO_MESSAGE_TYPE[PingRequest]
                writer.write(b"\0\0" + _varuint_to_bytes(message_type))
                await writer.drain()
                assert await asyncio.wait_for(reader.read(1), timeout=1) == b""
                await _wait_for(lambda: not api._clients)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await api.stop()
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)

    asyncio.run(run())


def test_noise_transport_handshake_still_requires_hello() -> None:
    async def run() -> None:
        device = Device(name="noise-hello", encryption_key=bytes(range(32)))
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writer = MemoryWriter()
        connection = NativeApiConnection(api, asyncio.StreamReader(), writer)  # type: ignore[arg-type]

        async def handshake(psk: bytes) -> None:
            connection._noise = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)

        async def read_message() -> None:
            await asyncio.Event().wait()

        with (
            patch("aioesphomeserver.native_api_server.CLIENT_HELLO_TIMEOUT", 0.02),
            patch.object(connection, "_perform_noise_handshake", handshake),
            patch.object(connection, "read_next_message", read_message),
        ):
            await asyncio.wait_for(connection.start(), timeout=1)
        assert writer.closed
        assert not connection.running

    asyncio.run(run())


def test_cancelled_noise_write_does_not_consume_an_unsent_nonce() -> None:
    async def run() -> None:
        initiator = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)
        responder = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)
        initiator.set_as_initiator()
        responder.set_as_responder()
        for peer in (initiator, responder):
            peer.set_psks(bytes(range(32)))
            peer.start_handshake()
        responder.read_message(initiator.write_message())
        initiator.read_message(responder.write_message())

        device = Device(name="noise-cancellation")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writer = MemoryWriter()
        connection = NativeApiConnection(api, asyncio.StreamReader(), writer)  # type: ignore[arg-type]
        connection._noise = responder

        await connection._write_lock.acquire()
        pending = asyncio.create_task(connection.write_message(PingResponse()))
        try:
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            connection._write_lock.release()

        message = HelloResponse(name="valid-after-cancel")
        await connection.write_message(message)
        assert len(writer.frames) == 1
        plaintext = initiator.decrypt(writer.frames[0][3:])
        assert plaintext[:2] == PROTO_TO_MESSAGE_TYPE[HelloResponse].to_bytes(2, "big")
        assert plaintext[4:] == message.SerializeToString()

    asyncio.run(run())


def test_homeassistant_response_must_come_from_an_action_recipient() -> None:
    async def run() -> None:
        device = Device(name="response-owner")
        api = NativeApiServer(name="_api", host="127.0.0.1", port=0)
        device.add_entity(api)
        server_task = asyncio.create_task(api.run())
        clients: list[APIClient] = []
        action_task = None
        try:
            await _wait_for(lambda: api.bound_port is not None)
            assert api.bound_port is not None
            clients = [APIClient("127.0.0.1", api.bound_port, keepalive=60) for _ in range(2)]
            for client in clients:
                await client.connect()
            recipient, other = clients
            calls: list[Any] = []
            recipient.subscribe_service_calls(calls.append)
            await _wait_for(lambda: any(client.subscribe_to_homeassistant_services for client in api._clients))

            action_task = asyncio.create_task(device.call_homeassistant_service("light.turn_on", wait_for_response=True))
            await _wait_for(lambda: bool(calls))
            other.send_homeassistant_action_response(calls[0].call_id, success=False)
            await asyncio.sleep(0.02)
            assert not action_task.done()
            recipient.send_homeassistant_action_response(calls[0].call_id, success=True)
            response = await asyncio.wait_for(action_task, timeout=1)
            assert response is not None and response.success
        finally:
            if action_task is not None:
                action_task.cancel()
                await asyncio.gather(action_task, return_exceptions=True)
            for client in clients:
                await client.disconnect()
            await api.stop()
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)

    asyncio.run(run())
