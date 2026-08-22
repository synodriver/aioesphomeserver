from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import random
import re
import socket
from inspect import getframeinfo, stack
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable

from aioesphomeapi.api_pb2 import DeviceInfoResponse
from aioesphomeapi.model import BluetoothProxyFeature
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from aioesphomeserver.basic_entity import BasicEntity
from aioesphomeserver.device_capabilities import DeviceCapabilitiesResponse
from aioesphomeserver.logger import format_log
from aioesphomeserver.services import SupportsResponseType

if TYPE_CHECKING:
    from aioesphomeserver.bluetooth_proxy import BluetoothProxy
    from aioesphomeserver.services import ServiceArgType, UserService
    from aioesphomeserver.voice_assistant import VoiceAssistant

logger = logging.getLogger(__name__)

MAX_DEVICE_NAME_LENGTH = 31
NOISE_PSK_LENGTH = 32


def _normalize_device_name(name: str) -> str:
    """Return an ESPHome-compatible node name used by API and mDNS."""
    normalized = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower())
    normalized = normalized.strip("-_")[:MAX_DEVICE_NAME_LENGTH].rstrip("-_")
    if not normalized:
        raise ValueError("device name must contain at least one letter or digit")
    return normalized


def _normalize_encryption_key(
    key: str | bytes | None,
) -> tuple[str | None, bytes | None]:
    """Validate an ESPHome Noise PSK and return base64 and raw forms."""
    if key is None:
        return None, None
    if isinstance(key, bytes):
        raw_key = key
    else:
        try:
            raw_key = base64.b64decode(key, validate=True)
        except (binascii.Error, ValueError) as err:
            raise ValueError(
                "encryption_key must be a base64-encoded 32-byte value"
            ) from err
    if len(raw_key) != NOISE_PSK_LENGTH:
        raise ValueError("encryption_key must contain exactly 32 bytes")
    return base64.b64encode(raw_key).decode("ascii"), raw_key


def _legacy_bluetooth_proxy_version(feature_flags: int) -> int:
    """Map feature flags to the capability set used by pre-1.9 clients."""
    if not feature_flags & BluetoothProxyFeature.PASSIVE_SCAN:
        return 0
    if not feature_flags & BluetoothProxyFeature.ACTIVE_CONNECTIONS:
        return 1
    if feature_flags & BluetoothProxyFeature.CACHE_CLEARING:
        return 5
    if feature_flags & BluetoothProxyFeature.PAIRING:
        return 4
    return 3


class Device:
    def __init__(
        self,
        name: str,
        mac_address: str | None = None,
        model: str | None = None,
        project_name: str | None = None,
        project_version: str | None = None,
        esphome_version: str = "0.0.1",
        manufacturer: str = "aioesphomeserver",
        friendly_name: str | None = None,
        suggested_area: str | None = None,
        network: str | None = None,
        board: str | None = None,
        platform: str | None = None,
        bluetooth_proxy: BluetoothProxy | None = None,
        voice_assistant: VoiceAssistant | None = None,
        encryption_key: str | bytes | None = None,
    ) -> None:
        self.name = _normalize_device_name(name)
        self.mac_address = mac_address or self._generate_mac_address()
        self.model = model
        self.project_name = project_name
        self.project_version = project_version
        self.esphome_version = esphome_version
        self.manufacturer = manufacturer
        self.friendly_name = friendly_name or (name if name != self.name else None)
        self.suggested_area = suggested_area
        self.network = network
        self.board = board
        self.platform = platform
        self.bluetooth_proxy = bluetooth_proxy
        if self.bluetooth_proxy is not None:
            self.bluetooth_proxy.device = self
        self.voice_assistant = voice_assistant
        if self.voice_assistant is not None:
            self.voice_assistant.device = self
        self.encryption_key, self.encryption_key_bytes = _normalize_encryption_key(
            encryption_key
        )
        self.entities: list[BasicEntity] = []
        self.services: list[UserService] = []
        self.zeroconf: AsyncZeroconf | None = None
        self.service_info: ServiceInfo | None = None
        self.running = True
        self.api_port: int | None = None
        self.web_port: int | None = None

    def _generate_mac_address(self) -> str:
        return "02:00:00:%02x:%02x:%02x" % (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
        )

    def _get_ip_address(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.254.254.254", 1))
            ip_address = s.getsockname()[0]
        except Exception:
            ip_address = "127.0.0.1"
        finally:
            s.close()
        return ip_address

    def get_ip_address(self) -> str:
        return self._get_ip_address()

    def _project_info(self) -> tuple[str, str]:
        if not self.project_name or "." not in self.project_name:
            return "", ""
        return self.project_name, self.project_version or "0.0.1"

    async def build_device_info_response(self) -> DeviceInfoResponse:
        project_name, project_version = self._project_info()
        response = DeviceInfoResponse(
            uses_password=False,
            name=self.name,
            mac_address=self.mac_address,
            esphome_version=self.esphome_version,
            model=self.model or "Python",
            project_name=project_name,
            project_version=project_version,
            webserver_port=self.web_port or 0,
            manufacturer=self.manufacturer,
            friendly_name=self.friendly_name or self.name,
            suggested_area=self.suggested_area or "",
            api_encryption_supported=self.encryption_key is not None,
            api_encryption_provisionable=False,
        )
        if self.bluetooth_proxy is not None:
            response.legacy_bluetooth_proxy_version = _legacy_bluetooth_proxy_version(
                self.bluetooth_proxy.feature_flags
            )
            response.bluetooth_proxy_feature_flags = self.bluetooth_proxy.feature_flags
            response.bluetooth_mac_address = (
                self.bluetooth_proxy.bluetooth_mac_address or self.mac_address
            )
        if self.voice_assistant is not None:
            response.legacy_voice_assistant_version = (
                self.voice_assistant.legacy_version
            )
            response.voice_assistant_feature_flags = self.voice_assistant.feature_flags
        return response

    async def build_device_capabilities_response(self) -> DeviceCapabilitiesResponse:
        response = DeviceCapabilitiesResponse()
        if self.bluetooth_proxy is not None:
            response.bluetooth_proxy.feature_flags = self.bluetooth_proxy.feature_flags
            response.bluetooth_proxy.mac_address = (
                self.bluetooth_proxy.bluetooth_mac_address or self.mac_address
            )
        if self.voice_assistant is not None:
            response.voice_assistant.feature_flags = self.voice_assistant.feature_flags
        return response

    async def log(self, level: int, tag: str, message: str) -> None:
        caller = getframeinfo(stack()[1][0])
        formatted_log = format_log(level, tag, caller.lineno, message)
        print(formatted_log)
        try:
            await self.publish(None, "log", (level, formatted_log))
        except Exception as e:
            logger.error(f"Error publishing log: {e}", exc_info=True)

    async def publish(
        self, publisher: BasicEntity | None, key: str, message: Any
    ) -> None:
        for entity in self.entities:
            if publisher == entity:
                continue
            try:
                if await entity.can_handle(key, message):
                    await entity.handle(key, message)
            except ConnectionResetError:
                logger.warning(f"Connection reset while publishing to {entity.name}")
            except Exception as e:
                logger.error(f"Error publishing to {entity.name}: {e}", exc_info=True)

    def add_entity(self, entity: BasicEntity) -> None:
        entity.device = self
        entity.key = len(self.entities) + 1

        existing_entity = [e for e in self.entities if e.object_id == entity.object_id]
        if len(existing_entity) > 0:
            raise ValueError(f"Duplicate object_id: {entity.object_id}")

        self.entities.append(entity)

    def add_service(
        self,
        name: str,
        callback: Callable[..., Any],
        *,
        arguments: Mapping[str, ServiceArgType | type[Any]] | None = None,
        supports_response: SupportsResponseType | str | int = SupportsResponseType.NONE,
    ) -> UserService:
        """Expose a Python callback as an ESPHome user-defined API action."""
        from aioesphomeserver.services import UserService

        service = UserService(
            name,
            callback,
            arguments=arguments,
            supports_response=supports_response,
        )
        if any(existing.name == service.name for existing in self.services):
            raise ValueError(f"Duplicate service name: {service.name}")
        if any(existing.key == service.key for existing in self.services):
            raise ValueError(f"Service key collision: {service.name}")
        self.services.append(service)
        return service

    def get_entity(self, object_id: str) -> BasicEntity | None:
        for entity in self.entities:
            if entity.object_id == object_id:
                return entity
        return None

    def get_entity_by_key(self, key: int) -> BasicEntity | None:
        if key <= 0 or key > len(self.entities):
            return None
        return self.entities[key - 1]

    async def run(self, api_port: int = 6053, web_port: int | None = 8080) -> None:
        from aioesphomeserver import NativeApiServer, WebServer

        self.api_port = api_port
        self.web_port = web_port

        api_server = NativeApiServer(name="_server", port=self.api_port)
        self.add_entity(api_server)
        if self.web_port is not None:
            self.add_entity(WebServer(name="_web_server", port=self.web_port))

        while self.running:
            try:
                async with asyncio.TaskGroup() as tg:
                    for entity in self.entities:
                        if hasattr(entity, "run"):
                            tg.create_task(entity.run())

                    await api_server.wait_started()
                    self.api_port = api_server.bound_port
                    self.zeroconf = await self.register_zeroconf(self.api_port)
                    tg.create_task(self.heartbeat())

            except ConnectionResetError:
                logger.warning("Connection reset. Restarting servers in 5 seconds...")
                await self.unregister_zeroconf()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("Device run cancelled. Shutting down...")
                break
            except Exception as e:
                logger.error(f"Unexpected error in device run: {e}", exc_info=True)
                await self.unregister_zeroconf()
                await asyncio.sleep(5)

        await self.shutdown()

    async def heartbeat(self) -> None:
        while self.running:
            try:
                for entity in self.entities:
                    if hasattr(entity, "check_connection"):
                        await entity.check_connection()
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
            except Exception as e:
                logger.error(f"Error in heartbeat: {e}", exc_info=True)

    async def shutdown(self) -> None:
        self.running = False
        for entity in self.entities:
            if hasattr(entity, "stop"):
                await entity.stop()
        await self.unregister_zeroconf()

    async def register_zeroconf(self, port: int) -> AsyncZeroconf | None:
        try:
            zeroconf = AsyncZeroconf()
            service_type = "_esphomelib._tcp.local."

            service_name = f"{self.name}.{service_type}"
            ip_address = self._get_ip_address()
            hostname = f"{self.name}.local."
            config_hash = hashlib.sha256(
                f"{self.name}:{self.project_name}:{self.project_version}".encode()
            ).hexdigest()[:8]
            project_name, project_version = self._project_info()

            properties = {
                "network": self.network or "wifi",
                "board": self.board or "esp01_1m",
                "platform": self.platform or "ESP8266",
                "mac": self.mac_address.replace(":", "").lower(),
                "version": self.esphome_version,
                "config_hash": config_hash,
                "friendly_name": self.friendly_name or self.name,
            }
            if project_name:
                properties["project_name"] = project_name
                properties["project_version"] = project_version
            if self.encryption_key is not None:
                properties["api_encryption"] = "Noise_NNpsk0_25519_ChaChaPoly_SHA256"

            service_info = ServiceInfo(
                service_type,
                service_name,
                addresses=[socket.inet_aton(ip_address)],
                port=port,
                properties=properties,
                server=hostname,
            )

            await zeroconf.async_register_service(service_info)
            self.service_info = service_info
            return zeroconf
        except Exception as e:
            logger.error(f"Error registering zeroconf: {e}", exc_info=True)
            return None

    async def unregister_zeroconf(self) -> None:
        if self.zeroconf and self.service_info:
            try:
                await self.zeroconf.async_unregister_service(self.service_info)
                await self.zeroconf.async_close()
            except Exception as e:
                logger.error(f"Error unregistering zeroconf: {e}", exc_info=True)
            finally:
                self.zeroconf = None
                self.service_info = None
