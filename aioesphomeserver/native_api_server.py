from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from aioesphomeapi.api_pb2 import AuthenticationRequest  # type: ignore
from aioesphomeapi.api_pb2 import AuthenticationResponse  # type: ignore
from aioesphomeapi.api_pb2 import DeviceInfoRequest  # type: ignore
from aioesphomeapi.api_pb2 import DisconnectRequest  # type: ignore
from aioesphomeapi.api_pb2 import DisconnectResponse  # type: ignore
from aioesphomeapi.api_pb2 import GetTimeRequest  # type: ignore
from aioesphomeapi.api_pb2 import GetTimeResponse  # type: ignore
from aioesphomeapi.api_pb2 import HelloRequest  # type: ignore
from aioesphomeapi.api_pb2 import HelloResponse  # type: ignore
from aioesphomeapi.api_pb2 import ListEntitiesDoneResponse  # type: ignore
from aioesphomeapi.api_pb2 import ListEntitiesRequest  # type: ignore
from aioesphomeapi.api_pb2 import PingRequest  # type: ignore
from aioesphomeapi.api_pb2 import PingResponse  # type: ignore
from aioesphomeapi.api_pb2 import SubscribeHomeassistantServicesRequest  # type: ignore
from aioesphomeapi.api_pb2 import SubscribeHomeAssistantStatesRequest  # type: ignore
from aioesphomeapi.api_pb2 import SubscribeLogsRequest  # type: ignore
from aioesphomeapi.api_pb2 import SubscribeLogsResponse  # type: ignore
from aioesphomeapi.api_pb2 import SubscribeStatesRequest  # type: ignore
from aioesphomeapi.core import MESSAGE_TYPE_TO_PROTO
from noise.connection import NoiseConnection
from noise.exceptions import NoiseInvalidMessage

from .basic_entity import BasicEntity
from .device_capabilities import DeviceCapabilitiesRequest

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

    from google.protobuf.message import Message


API_VERSION_MAJOR = 1
API_VERSION_MINOR = 15
MAX_MESSAGE_SIZE = 10 * 1024 * 1024
MAX_NOISE_FRAME_SIZE = 65535
NOISE_HANDSHAKE_TIMEOUT = 10
NOISE_PROTOCOL_NAME = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"
NOISE_PROLOGUE = b"NoiseAPIInit"
PROTO_TO_MESSAGE_TYPE = {
    proto: type_id for type_id, proto in MESSAGE_TYPE_TO_PROTO.items()
}

logger = logging.getLogger(__name__)


class NativeApiProtocolError(Exception):
    """Raised when a client sends an invalid native API frame."""


def _varuint_to_bytes(value: int) -> bytes:
    """Encode a non-negative integer using protobuf varuint encoding."""
    if value < 0:
        raise ValueError("varuint cannot encode a negative value")

    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


class NativeApiConnection:
    """One plaintext or Noise-encrypted ESPHome native API connection."""

    def __init__(
        self,
        server: "NativeApiServer",
        reader: "StreamReader",
        writer: "StreamWriter",
    ) -> None:
        self.server = server
        self.reader = reader
        self.writer = writer
        self.subscribe_to_logs = False
        self.subscribe_to_states = False
        self.running = True
        self._write_lock = asyncio.Lock()
        self._noise: NoiseConnection | None = None

    async def start(self) -> None:
        try:
            if self.server.device.encryption_key_bytes is not None:
                async with asyncio.timeout(NOISE_HANDSHAKE_TIMEOUT):
                    await self._perform_noise_handshake(
                        self.server.device.encryption_key_bytes
                    )
            while self.running:
                message = await self.read_next_message()
                if message is not None:
                    await self.handle_message(message)
        except (
            asyncio.IncompleteReadError,
            ConnectionResetError,
            BrokenPipeError,
            NoiseInvalidMessage,
            NativeApiProtocolError,
            TimeoutError,
        ):
            logger.debug("Native API client disconnected")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Native API connection failed")
        finally:
            await self.stop()

    async def handle_message(self, message: "Message") -> None:
        await self.server.log(f"{type(message).__name__}: {message}")

        if type(message) is HelloRequest:
            await self.write_message(
                HelloResponse(
                    api_version_major=API_VERSION_MAJOR,
                    api_version_minor=API_VERSION_MINOR,
                    server_info="aioesphomeserver",
                    name=self.server.device.name,
                )
            )
        elif type(message) is AuthenticationRequest:
            await self.write_message(AuthenticationResponse(invalid_password=False))
        elif type(message) is DisconnectRequest:
            await self.write_message(DisconnectResponse())
            self.running = False
        elif type(message) is SubscribeLogsRequest:
            self.subscribe_to_logs = True
        elif type(message) is PingRequest:
            await self.write_message(PingResponse())
        elif type(message) is GetTimeRequest:
            await self.write_message(
                GetTimeResponse(epoch_seconds=int(time.time()), timezone="UTC")
            )
        elif type(message) is SubscribeStatesRequest:
            self.subscribe_to_states = True
            await self.server.send_all_states(self)
        else:
            await self.server.handle_client_request(self, message)

    async def log(self, level: int, message: str) -> None:
        await self.write_message(
            SubscribeLogsResponse(level=level, message=message.encode("utf-8"))
        )

    async def read_next_message(self) -> "Message | None":
        if self._noise is not None:
            return await self._read_noise_message()

        preamble = await self._read_varuint()
        if preamble != 0:
            raise ValueError(f"unsupported native API preamble: {preamble}")

        length = await self._read_varuint()
        if length > MAX_MESSAGE_SIZE:
            raise ValueError(f"native API message is too large: {length} bytes")
        message_type = await self._read_varuint()
        payload = await self.reader.readexactly(length)

        message_class = MESSAGE_TYPE_TO_PROTO.get(message_type)
        if message_class is None:
            logger.warning("Ignoring unknown native API message type %s", message_type)
            return None

        message = message_class()
        message.ParseFromString(payload)
        return message

    async def write_message(self, message: "Message | None") -> None:
        if message is None or not self.running:
            return

        message_type = PROTO_TO_MESSAGE_TYPE.get(type(message))
        if message_type is None:
            raise ValueError(
                f"unknown native API protobuf type: {type(message).__name__}"
            )

        payload = message.SerializeToString()
        if self._noise is None:
            frame = b"".join(
                (
                    b"\0",
                    _varuint_to_bytes(len(payload)),
                    _varuint_to_bytes(message_type),
                    payload,
                )
            )
        else:
            if len(payload) > MAX_NOISE_FRAME_SIZE - 20:
                raise ValueError(
                    f"native API message is too large for Noise: {len(payload)} bytes"
                )
            plaintext = b"".join(
                (
                    message_type.to_bytes(2, "big"),
                    len(payload).to_bytes(2, "big"),
                    payload,
                )
            )
            encrypted = self._noise.encrypt(plaintext)
            frame = b"\x01" + len(encrypted).to_bytes(2, "big") + encrypted
        async with self._write_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def _perform_noise_handshake(self, psk: bytes) -> None:
        client_hello = await self._read_noise_frame()
        prologue = NOISE_PROLOGUE + len(client_hello).to_bytes(2, "big") + client_hello

        server_hello = b"".join(
            (
                b"\x01",
                self.server.device.name.encode("utf-8"),
                b"\0",
                self.server.device.mac_address.replace(":", "").lower().encode("ascii"),
                b"\0",
            )
        )
        await self._write_noise_frame(server_hello)

        noise = NoiseConnection.from_name(NOISE_PROTOCOL_NAME)
        noise.set_as_responder()
        noise.set_psks(psk)
        noise.set_prologue(prologue)
        noise.start_handshake()

        handshake = await self._read_noise_frame()
        if not handshake or handshake[0] != 0:
            await self._write_noise_rejection("Bad handshake error byte")
            raise NativeApiProtocolError("invalid Noise handshake frame")
        try:
            noise.read_message(handshake[1:])
            response = noise.write_message()
        except Exception as err:
            await self._write_noise_rejection("Handshake MAC failure")
            raise NativeApiProtocolError("Noise handshake failed") from err

        await self._write_noise_frame(b"\0" + response)
        self._noise = noise

    async def _read_noise_message(self) -> "Message | None":
        assert self._noise is not None
        decrypted = self._noise.decrypt(await self._read_noise_frame())
        if len(decrypted) < 4:
            raise NativeApiProtocolError("decrypted native API message is too short")
        message_type = int.from_bytes(decrypted[:2], "big")
        payload_length = int.from_bytes(decrypted[2:4], "big")
        payload = decrypted[4:]
        if payload_length != len(payload):
            raise NativeApiProtocolError(
                "decrypted native API message has an invalid length"
            )

        message_class = MESSAGE_TYPE_TO_PROTO.get(message_type)
        if message_class is None:
            logger.warning("Ignoring unknown native API message type %s", message_type)
            return None
        message = message_class()
        message.ParseFromString(payload)
        return message

    async def _read_noise_frame(self) -> bytes:
        header = await self.reader.readexactly(3)
        if header[0] != 1:
            await self._write_noise_rejection("Bad indicator byte")
            raise NativeApiProtocolError(f"unsupported Noise indicator: {header[0]}")
        length = int.from_bytes(header[1:3], "big")
        if length > MAX_NOISE_FRAME_SIZE:
            raise NativeApiProtocolError(f"Noise frame is too large: {length} bytes")
        return await self.reader.readexactly(length)

    async def _write_noise_frame(self, payload: bytes) -> None:
        if len(payload) > MAX_NOISE_FRAME_SIZE:
            raise ValueError(f"Noise frame is too large: {len(payload)} bytes")
        self.writer.write(b"\x01" + len(payload).to_bytes(2, "big") + payload)
        await self.writer.drain()

    async def _write_noise_rejection(self, reason: str) -> None:
        await self._write_noise_frame(b"\x01" + reason.encode("ascii"))

    async def _read_varuint(self) -> int:
        result = 0
        for bit_position in range(0, 70, 7):
            value = (await self.reader.readexactly(1))[0]
            result |= (value & 0x7F) << bit_position
            if not value & 0x80:
                return result
        raise ValueError("invalid native API varuint")

    async def stop(self) -> None:
        if not self.running and self.writer.is_closing():
            return
        self.running = False
        if not self.writer.is_closing():
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass


class NativeApiServer(BasicEntity):
    """ESPHome native API server with optional Noise encryption."""

    def __init__(
        self,
        *args: Any,
        port: int = 6053,
        host: str = "0.0.0.0",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.port = port
        self.host = host
        self.bound_port: int | None = None
        self._clients: set[NativeApiConnection] = set()
        self.server: asyncio.Server | None = None
        self._started = asyncio.Event()

    async def run(self) -> None:
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        sockets = self.server.sockets or []
        self.bound_port = sockets[0].getsockname()[1] if sockets else self.port
        self._started.set()
        await self.device.log(2, "api", f"Starting on {self.host}:{self.bound_port}")
        async with self.server:
            await self.server.serve_forever()

    async def wait_started(self) -> None:
        """Wait until the TCP listener has successfully bound its port."""
        await self._started.wait()

    async def log(self, message: str) -> None:
        for client in tuple(self._clients):
            if client.subscribe_to_logs:
                await client.log(3, message)

    async def handle_client(
        self, reader: "StreamReader", writer: "StreamWriter"
    ) -> None:
        connection = NativeApiConnection(self, reader, writer)
        self._clients.add(connection)
        try:
            await connection.start()
        finally:
            self._clients.discard(connection)
            bluetooth_proxy = self.device.bluetooth_proxy
            if bluetooth_proxy is not None:
                await bluetooth_proxy.on_api_client_disconnected(connection)
            voice_assistant = self.device.voice_assistant
            if voice_assistant is not None:
                await voice_assistant.on_api_client_disconnected(connection)

    async def handle_client_request(
        self, client: NativeApiConnection, message: "Message"
    ) -> None:
        if type(message) in (
            SubscribeHomeassistantServicesRequest,
            SubscribeHomeAssistantStatesRequest,
        ):
            return
        if type(message) is ListEntitiesRequest:
            await self.handle_list_entities(client)
            return
        if type(message) is DeviceInfoRequest:
            await client.write_message(await self.device.build_device_info_response())
            return
        if type(message) is DeviceCapabilitiesRequest:
            await client.write_message(
                await self.device.build_device_capabilities_response()
            )
            return

        bluetooth_proxy = self.device.bluetooth_proxy
        if bluetooth_proxy is not None and await bluetooth_proxy.handle_api_message(
            client, message
        ):
            return
        voice_assistant = self.device.voice_assistant
        if voice_assistant is not None and await voice_assistant.handle_api_message(
            client, message
        ):
            return
        await self.device.publish(self, "client_request", message)

    async def handle_list_entities(self, client: NativeApiConnection) -> None:
        for entity in self.device.entities:
            message = await entity.build_list_entities_response()
            if message is not None:
                await client.write_message(message)
        await client.write_message(ListEntitiesDoneResponse())

    async def send_all_states(self, client: NativeApiConnection) -> None:
        for entity in self.device.entities:
            message = await entity.build_state_response()
            if message is not None:
                await client.write_message(message)

    async def handle(self, key: str, message: Any) -> None:
        if key == "state_change":
            for client in tuple(self._clients):
                if client.subscribe_to_states:
                    await client.write_message(message)
        elif key == "log":
            level, text = message
            for client in tuple(self._clients):
                if client.subscribe_to_logs:
                    await client.log(level, text)

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.bound_port = None
        self._started.clear()
        if self._clients:
            await asyncio.gather(*(client.stop() for client in tuple(self._clients)))
            self._clients.clear()

    async def restart(self) -> None:
        await self.stop()
        await self.run()
