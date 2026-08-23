from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
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
from aioesphomeapi.api_pb2 import HomeassistantActionRequest  # type: ignore
from aioesphomeapi.api_pb2 import HomeassistantActionResponse  # type: ignore
from aioesphomeapi.api_pb2 import ListEntitiesDoneResponse  # type: ignore
from aioesphomeapi.api_pb2 import ExecuteServiceRequest  # type: ignore
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

from aioesphomeserver.basic_entity import BasicEntity
from aioesphomeserver.device_capabilities import DeviceCapabilitiesRequest

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

    from google.protobuf.message import Message

    from aioesphomeserver.device import Device

API_VERSION_MAJOR = 1
API_VERSION_MINOR = 15
# ESPHome's native API uses a uint16 length on the wire.  Keep the plaintext
# path aligned with the Noise path and the official Python client.
MAX_MESSAGE_SIZE = 65535
MAX_NOISE_FRAME_SIZE = 65535
NOISE_HANDSHAKE_TIMEOUT = 10
CLIENT_HELLO_TIMEOUT = 60
HOMEASSISTANT_ACTION_TIMEOUT = 30.0
DEFAULT_MAX_CONNECTIONS = 6
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
        self.subscribe_to_homeassistant_services = False
        self.running = True
        self._write_lock = asyncio.Lock()
        self._noise: NoiseConnection | None = None
        self._service_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        try:
            device = self.server.attached_device
            if device.encryption_key_bytes is not None:
                async with asyncio.timeout(NOISE_HANDSHAKE_TIMEOUT):
                    await self._perform_noise_handshake(
                        device.encryption_key_bytes
                    )
            first_message = True
            while self.running:
                if first_message and self._noise is None:
                    async with asyncio.timeout(CLIENT_HELLO_TIMEOUT):
                        message = await self.read_next_message()
                else:
                    message = await self.read_next_message()
                first_message = False
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
        await self.server.log(type(message).__name__)

        if type(message) is HelloRequest:
            await self.write_message(
                HelloResponse(
                    api_version_major=API_VERSION_MAJOR,
                    api_version_minor=API_VERSION_MINOR,
                    server_info="aioesphomeserver",
                    name=self.server.attached_device.name,
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
        elif type(message) is ExecuteServiceRequest:
            task = asyncio.create_task(self.server.execute_service(self, message))
            self._service_tasks.add(task)
            task.add_done_callback(self._service_tasks.discard)
        elif type(message) is HomeassistantActionResponse:
            self.server.handle_homeassistant_action_response(message)
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
            raise NativeApiProtocolError(f"unsupported native API preamble: {preamble}")

        length = await self._read_varuint()
        if length > MAX_MESSAGE_SIZE:
            raise NativeApiProtocolError(
                f"native API message is too large: {length} bytes"
            )
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
            if len(payload) > MAX_MESSAGE_SIZE:
                raise NativeApiProtocolError(
                    f"native API message is too large: {len(payload)} bytes"
                )
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
                self.server.attached_device.name.encode("utf-8"),
                b"\0",
                self.server.attached_device.mac_address.replace(":", "").lower().encode("ascii"),
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
        for bit_position in range(0, 28, 7):
            value = (await self.reader.readexactly(1))[0]
            result |= (value & 0x7F) << bit_position
            if not value & 0x80:
                return result
        raise NativeApiProtocolError("invalid native API varuint")

    async def stop(self, *, wait_closed: bool = True) -> None:
        if not self.running and self.writer.is_closing():
            return
        self.running = False
        if self._service_tasks:
            for task in self._service_tasks:
                task.cancel()
            await asyncio.gather(
                *(task for task in tuple(self._service_tasks) if not task.done()),
                return_exceptions=True,
            )
            self._service_tasks.clear()
        if not self.writer.is_closing():
            self.writer.close()
            if not wait_closed:
                return
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
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.port = port
        self.host = host
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        self.max_connections = max_connections
        self.bound_port: int | None = None
        self._clients: set[NativeApiConnection] = set()
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._next_homeassistant_call_id = 1
        self._homeassistant_action_futures: dict[
            int, asyncio.Future[HomeassistantActionResponse]
        ] = {}
        self._homeassistant_action_clients: dict[
            int, set[NativeApiConnection]
        ] = {}
        self.server: asyncio.Server | None = None
        self._started = asyncio.Event()

    @property
    def attached_device(self) -> Device:
        if self.device is None:
            raise RuntimeError("Native API server is not attached to a device")
        return self.device

    async def run(self) -> None:
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        sockets: Any = self.server.sockets or []
        self.bound_port = sockets[0].getsockname()[1] if sockets else self.port
        self._started.set()
        await self.attached_device.log(
            2, "api", f"Starting on {self.host}:{self.bound_port}"
        )
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
        if len(self._clients) >= self.max_connections:
            logger.warning("Rejecting native API client: connection limit reached")
            writer.close()
            await writer.wait_closed()
            return
        connection = NativeApiConnection(self, reader, writer)
        self._clients.add(connection)
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
        try:
            await connection.start()
        finally:
            self._remove_homeassistant_action_client(connection)
            self._clients.discard(connection)
            bluetooth_proxy = self.attached_device.bluetooth_proxy
            if bluetooth_proxy is not None:
                await bluetooth_proxy.on_api_client_disconnected(connection)
            voice_assistant = self.attached_device.voice_assistant
            if voice_assistant is not None:
                await voice_assistant.on_api_client_disconnected(connection)
            if task is not None:
                self._client_tasks.discard(task)

    async def handle_client_request(
        self, client: NativeApiConnection, message: "Message"
    ) -> None:
        if type(message) is SubscribeHomeassistantServicesRequest:
            client.subscribe_to_homeassistant_services = True
            return
        if type(message) is SubscribeHomeAssistantStatesRequest:
            return
        if type(message) is ListEntitiesRequest:
            await self.handle_list_entities(client)
            return
        if type(message) is DeviceInfoRequest:
            await client.write_message(
                await self.attached_device.build_device_info_response()
            )
            return
        if type(message) is DeviceCapabilitiesRequest:
            await client.write_message(
                await self.attached_device.build_device_capabilities_response()
            )
            return

        bluetooth_proxy = self.attached_device.bluetooth_proxy
        if bluetooth_proxy is not None and await bluetooth_proxy.handle_api_message(
            client, message
        ):
            return
        voice_assistant = self.attached_device.voice_assistant
        if voice_assistant is not None and await voice_assistant.handle_api_message(
            client, message
        ):
            return
        await self.attached_device.publish(self, "client_request", message)

    async def send_homeassistant_action(
        self,
        service: str,
        *,
        data: Mapping[str, str] | None = None,
        data_template: Mapping[str, str] | None = None,
        variables: Mapping[str, str] | None = None,
        is_event: bool = False,
        wait_for_response: bool = False,
        response_template: str | None = None,
        timeout: float = HOMEASSISTANT_ACTION_TIMEOUT,
    ) -> HomeassistantActionResponse | None:
        """Send a Home Assistant service call or event to subscribed clients."""
        if not service:
            raise ValueError("Home Assistant service name cannot be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if response_template is not None and not wait_for_response:
            raise ValueError("response_template requires wait_for_response=True")
        for values in (data, data_template, variables):
            if values is not None and not isinstance(values, Mapping):
                raise TypeError("Home Assistant action maps must be mappings")
            for key, value in (values or {}).items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise TypeError(
                        "Home Assistant action maps require string keys and values"
                    )

        subscribers = tuple(
            client
            for client in self._clients
            if client.subscribe_to_homeassistant_services and client.running
        )
        if not subscribers:
            if wait_for_response:
                raise RuntimeError(
                    "Home Assistant has not subscribed to service calls"
                )
            logger.warning(
                "Dropping Home Assistant %s %r: no subscribed client",
                "event" if is_event else "service call",
                service,
            )
            return None

        request = HomeassistantActionRequest(
            service=service,
            is_event=is_event,
            wants_response=wait_for_response,
            response_template=response_template or "",
        )
        for field, values in (
            (request.data, data),
            (request.data_template, data_template),
            (request.variables, variables),
        ):
            for key, value in (values or {}).items():
                entry = field.add()
                entry.key = key
                entry.value = value

        future: asyncio.Future[HomeassistantActionResponse] | None = None
        if wait_for_response:
            call_id = self._next_homeassistant_call_id
            self._next_homeassistant_call_id = (
                self._next_homeassistant_call_id + 1
            ) & 0xFFFFFFFF
            if self._next_homeassistant_call_id == 0:
                self._next_homeassistant_call_id = 1
            request.call_id = call_id
            future = asyncio.get_running_loop().create_future()
            self._homeassistant_action_futures[call_id] = future
            self._homeassistant_action_clients[call_id] = set(subscribers)

        try:
            sent = 0
            for client in subscribers:
                try:
                    await client.write_message(request)
                except (ConnectionError, OSError, NativeApiProtocolError) as err:
                    logger.debug(
                        "Home Assistant action %r could not be sent to a client: %s",
                        service,
                        err,
                    )
                    self._remove_homeassistant_action_client(client)
                else:
                    sent += 1
            if sent == 0:
                if future is not None:
                    raise RuntimeError(
                        "Home Assistant action could not be sent to any subscriber"
                    )
                return None
            if future is None:
                return None
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Home Assistant action {service!r} timed out after {timeout:g}s"
            ) from None
        finally:
            if future is not None:
                self._homeassistant_action_futures.pop(request.call_id, None)
                self._homeassistant_action_clients.pop(request.call_id, None)

    def handle_homeassistant_action_response(
        self, response: HomeassistantActionResponse
    ) -> None:
        future = self._homeassistant_action_futures.get(response.call_id)
        if future is not None and not future.done():
            future.set_result(response)

    def _remove_homeassistant_action_client(self, client: NativeApiConnection) -> None:
        """Remove a disconnected client from pending Home Assistant calls."""
        for call_id, clients in tuple(self._homeassistant_action_clients.items()):
            clients.discard(client)
            if clients:
                continue
            future = self._homeassistant_action_futures.get(call_id)
            if future is not None and not future.done():
                future.set_exception(
                    RuntimeError("all Home Assistant action subscribers disconnected")
                )

    def _fail_homeassistant_actions(self, reason: str) -> None:
        for future in tuple(self._homeassistant_action_futures.values()):
            if not future.done():
                future.set_exception(RuntimeError(reason))

    async def handle_list_entities(self, client: NativeApiConnection) -> None:
        for entity in self.attached_device.entities:
            message = await entity.build_list_entities_response()
            if message is not None:
                await client.write_message(message)
        for service in self.attached_device.services:
            await client.write_message(service.list_entities_response())
        await client.write_message(ListEntitiesDoneResponse())

    async def execute_service(
        self, client: NativeApiConnection, message: ExecuteServiceRequest
    ) -> None:
        for service in self.attached_device.services:
            if message.key == service.key:
                await service.execute(message, client)
                return
        logger.warning("Ignoring unknown user service key %s", message.key)

    async def send_all_states(self, client: NativeApiConnection) -> None:
        for entity in self.attached_device.entities:
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
        self._fail_homeassistant_actions("Native API server stopped")
        if self.server is not None:
            self.server.close()
            self.server = None
        self.bound_port = None
        self._started.clear()
        clients = tuple(self._clients)
        tasks = tuple(
            task
            for task in self._client_tasks
            if task is not asyncio.current_task()
        )
        if clients:
            await asyncio.gather(
                *(client.stop(wait_closed=False) for client in clients),
                return_exceptions=True,
            )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()
        self._client_tasks.clear()

    async def restart(self) -> None:
        await self.stop()
        await self.run()
