import asyncio
import gc
from typing import Any, cast
from unittest.mock import patch

import pytest
from aioesphomeapi.api_pb2 import (
    HelloRequest,
    HelloResponse,
    HomeassistantActionResponse,
    PingResponse,
)
from noise.connection import NoiseConnection

from aioesphomeserver import Device, NativeApiServer
from aioesphomeserver.native_api_server import (
    NOISE_PROTOCOL_NAME,
    NativeApiConnection,
)


class MemoryWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.frames.append(data)

    async def drain(self) -> None:
        pass

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


def noise_pair() -> tuple[NoiseConnection, NoiseConnection]:
    initiator = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)
    responder = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)
    initiator.set_as_initiator()
    responder.set_as_responder()
    for connection in (initiator, responder):
        connection.set_psks(bytes(range(32)))
        connection.start_handshake()
    responder.read_message(initiator.write_message())
    initiator.read_message(responder.write_message())
    return initiator, responder


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "noise"])
def test_unknown_first_frame_does_not_disable_hello_timeout(encrypted: bool) -> None:
    async def run() -> None:
        device = Device(
            name="hello-timeout",
            encryption_key=bytes(range(32)) if encrypted else None,
        )
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        reader = asyncio.StreamReader()
        writer = MemoryWriter()
        connection = NativeApiConnection(api, reader, cast(Any, writer))
        if encrypted:
            initiator, responder = noise_pair()
            payload = initiator.encrypt(b"\x7f\xff\0\0")
            reader.feed_data(b"\x01" + len(payload).to_bytes(2, "big") + payload)

            async def handshake(_key: bytes) -> None:
                connection._noise = responder
        else:
            reader.feed_data(b"\0\0\xff\x7f")

            async def handshake(_key: bytes) -> None:
                raise AssertionError("plaintext cannot perform a Noise handshake")

        with (
            patch("aioesphomeserver.native_api_server.CLIENT_HELLO_TIMEOUT", 0.01),
            patch.object(connection, "_perform_noise_handshake", handshake),
        ):
            await asyncio.wait_for(connection.start(), timeout=0.3)
        assert writer.closed

    asyncio.run(run())


def test_cancelled_noise_write_does_not_advance_nonce() -> None:
    async def run() -> None:
        device = Device(name="nonce")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writer = MemoryWriter()
        connection = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
        initiator, connection._noise = noise_pair()
        await connection._write_lock.acquire()
        waiting = asyncio.create_task(connection.write_message(PingResponse()))
        try:
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        finally:
            connection._write_lock.release()
        await connection.write_message(PingResponse())
        assert len(writer.frames) == 1
        assert initiator.decrypt(writer.frames[0][3:]) == b"\0\x08\0\0"

    asyncio.run(run())


def test_homeassistant_action_response_must_come_from_recipient() -> None:
    async def run() -> None:
        device = Device(name="action-recipients")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        recipient = NativeApiConnection(
            api, asyncio.StreamReader(), cast(Any, MemoryWriter())
        )
        other = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, MemoryWriter()))
        recipient.subscribe_to_homeassistant_services = True
        api._clients.update((recipient, other))
        task = asyncio.create_task(api.send_homeassistant_action(
            "light.turn_on", wait_for_response=True, timeout=1
        ))
        try:
            await asyncio.sleep(0)
            call_id = next(iter(api._homeassistant_action_futures))
            await other.handle_message(HomeassistantActionResponse(
                call_id=call_id, success=False
            ))
            assert not api._homeassistant_action_futures[call_id].done()
            await recipient.handle_message(HomeassistantActionResponse(
                call_id=call_id, success=True
            ))
            response = await task
            assert response is not None and response.success
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_stopped_connection_does_not_send_queued_message() -> None:
    async def run() -> None:
        device = Device(name="stopped-writer")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writer = MemoryWriter()
        connection = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
        await connection._write_lock.acquire()
        task = asyncio.create_task(connection.write_message(HelloRequest()))
        await asyncio.sleep(0)
        connection.running = False
        connection._write_lock.release()
        await task
        assert not writer.frames

    asyncio.run(run())


def test_failed_homeassistant_action_sends_do_not_leak_future_exception() -> None:
    class FailedWriter(MemoryWriter):
        async def drain(self) -> None:
            raise ConnectionError("client disconnected")

    async def run() -> None:
        device = Device(name="failed-action")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        connection = NativeApiConnection(
            api, asyncio.StreamReader(), cast(Any, FailedWriter())
        )
        connection.subscribe_to_homeassistant_services = True
        api._clients.add(connection)
        errors: list[dict[str, Any]] = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        with pytest.raises(RuntimeError, match="could not be sent"):
            await api.send_homeassistant_action("light.turn_on", wait_for_response=True)
        await asyncio.sleep(0)
        assert not api._homeassistant_action_futures
        assert not errors

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["state", "log", "time", "subscription"])
def test_disconnected_subscriber_does_not_interrupt_broadcast(kind: str) -> None:
    class FailedWriter(MemoryWriter):
        async def drain(self) -> None:
            raise ConnectionError("client disconnected")

    async def run() -> None:
        device = Device(name="broadcast")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        failed_writer = FailedWriter()
        writer = MemoryWriter()
        failed = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, failed_writer))
        healthy = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
        for client in (failed, healthy):
            client.subscribe_to_states = True
            client.subscribe_to_logs = True
            client.log_level = 3
        api._clients.update((failed, healthy))
        api._homeassistant_state_clients.update((failed, healthy))
        if kind == "state":
            await api.handle("state_change", PingResponse())
        elif kind == "log":
            await api.log("broadcast test")
        elif kind == "time":
            await api.request_time()
        else:
            await api.send_homeassistant_state_subscription("sensor.test")
        assert failed_writer.closed
        assert not failed.running
        assert healthy.running
        assert len(writer.frames) == 1

    asyncio.run(run())


def test_broadcast_sends_to_clients_concurrently() -> None:
    async def run() -> None:
        class BlockingWriter(MemoryWriter):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def drain(self) -> None:
                self.started.set()
                await self.release.wait()

        device = Device(name="parallel-broadcast")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writers = (BlockingWriter(), BlockingWriter())
        clients = tuple(
            NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
            for writer in writers
        )
        api._clients.update(clients)
        task = asyncio.create_task(api.request_time())
        try:
            await asyncio.wait_for(
                asyncio.gather(*(writer.started.wait() for writer in writers)), 1
            )
            assert not task.done()
        finally:
            for writer in writers:
                writer.release.set()
            await task

    asyncio.run(run())


@pytest.mark.parametrize("failed_peer", [False, True], ids=["slow", "failed"])
def test_parallel_action_sends_keep_first_response(failed_peer: bool) -> None:
    async def run() -> None:
        class BlockingWriter(MemoryWriter):
            def __init__(self, *, blocked: bool = False) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()
                if not blocked:
                    self.release.set()

            async def drain(self) -> None:
                self.started.set()
                await self.release.wait()
                if failed_peer and self is writers[0]:
                    raise ConnectionError("client disconnected")

        device = Device(name="parallel-action")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writers = (BlockingWriter(blocked=True), BlockingWriter(), BlockingWriter())
        clients = tuple(
            NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
            for writer in writers
        )
        for client in clients:
            client.subscribe_to_homeassistant_services = True
        api._clients.update(clients)
        task = asyncio.create_task(api.send_homeassistant_action(
            "light.turn_on", wait_for_response=True
        ))
        try:
            await asyncio.wait_for(
                asyncio.gather(*(writer.started.wait() for writer in writers)), 1
            )
            call_id = next(iter(api._homeassistant_action_futures))
            first = HomeassistantActionResponse(call_id=call_id, success=True)
            api.handle_homeassistant_action_response(clients[1], first)
            api.handle_homeassistant_action_response(
                clients[2], HomeassistantActionResponse(call_id=call_id, success=False)
            )
            assert not task.done()
            writers[0].release.set()
            assert await asyncio.wait_for(task, 1) == first
            assert not api._homeassistant_action_futures
            assert not api._homeassistant_action_clients
        finally:
            writers[0].release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["broadcast", "action"])
def test_cancelled_parallel_send_cancels_all_writers(kind: str) -> None:
    async def run() -> None:
        class BlockingWriter(MemoryWriter):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.cancelled = False

            async def drain(self) -> None:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

        device = Device(name="parallel-cancel")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writers = (BlockingWriter(), BlockingWriter())
        clients = tuple(
            NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
            for writer in writers
        )
        for client in clients:
            client.subscribe_to_homeassistant_services = True
        api._clients.update(clients)
        task = asyncio.create_task(
            api.request_time() if kind == "broadcast" else api.send_homeassistant_action(
                "light.turn_on", wait_for_response=True
            )
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*(writer.started.wait() for writer in writers)), 1
            )
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert all(writer.cancelled for writer in writers)
            assert not api._homeassistant_action_futures
            assert not api._homeassistant_action_clients
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "noise"])
def test_parallel_broadcasts_preserve_connection_message_order(encrypted: bool) -> None:
    async def run() -> None:
        class BlockingWriter(MemoryWriter):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def drain(self) -> None:
                self.started.set()
                await self.release.wait()

        device = Device(name="parallel-order")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        writer = BlockingWriter()
        client = NativeApiConnection(api, asyncio.StreamReader(), cast(Any, writer))
        reader = asyncio.StreamReader()
        decoder = NativeApiConnection(api, reader, cast(Any, MemoryWriter()))
        if encrypted:
            decoder._noise, client._noise = noise_pair()
        messages = (HelloResponse(name="first"), HelloResponse(name="second"))
        first = asyncio.create_task(api._broadcast_message((client,), messages[0]))
        second = None
        try:
            await asyncio.wait_for(writer.started.wait(), 1)
            second = asyncio.create_task(api._broadcast_message((client,), messages[1]))
            await asyncio.sleep(0)
            writer.release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 1)
            reader.feed_data(b"".join(writer.frames))
            for message in messages:
                assert await asyncio.wait_for(decoder.read_next_message(), 1) == message
        finally:
            writer.release.set()
            tasks = (first,) if second is None else (first, second)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(run())


def test_cancelled_action_after_all_send_failures_consumes_future_exception() -> None:
    async def run() -> None:
        failures = 0

        class FailedWriter(MemoryWriter):
            async def drain(self) -> None:
                nonlocal failures
                failures += 1
                if failures == 2:
                    asyncio.get_running_loop().call_soon(task.cancel)
                raise ConnectionError("client disconnected")

        device = Device(name="failed-action-cancel")
        api = NativeApiServer(name="_api")
        device.add_entity(api)
        for _ in range(2):
            client = NativeApiConnection(
                api, asyncio.StreamReader(), cast(Any, FailedWriter())
            )
            client.subscribe_to_homeassistant_services = True
            api._clients.add(client)
        errors: list[dict[str, Any]] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: errors.append(context)
        )
        task = asyncio.create_task(api.send_homeassistant_action(
            "light.turn_on", wait_for_response=True
        ))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert failures == 2
        assert not api._homeassistant_action_futures
        assert not api._homeassistant_action_clients
        del task
        gc.collect()
        await asyncio.sleep(0)
        assert not errors

    asyncio.run(run())
