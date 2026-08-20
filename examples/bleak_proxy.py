"""Bleak-backed Bluetooth proxy example for Windows and Linux.

The proxy itself is backend agnostic. This example is intentionally separate
so applications can replace Bleak with another scanner/client library. It uses
the host's real Bluetooth adapter; it is not a no-hardware simulator.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

# Running this file directly sets sys.path[0] to examples/. Keep the repository
# root first so the example uses the edited source tree instead of an older
# installed aioesphomeserver package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aioesphomeapi.model import BluetoothProxyFeature
from bleak import BleakClient, BleakError, BleakScanner
from bleak.assigned_numbers import AdvertisementDataType
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

import aioesphomeserver
from aioesphomeserver import (
    BluetoothAdvertisement,
    BluetoothGATTCharacteristic,
    BluetoothGATTDescriptor,
    BluetoothGATTService,
    BluetoothProxy,
    Device,
    TextSensorEntity,
    bluetooth_address_to_int,
    bluetooth_address_to_str,
)

logger = logging.getLogger(__name__)

# BlueZ requires at least one AdvertisementMonitor pattern for passive scans.
# These are the same flags used by Home Assistant's habluetooth scanner and
# collectively match normal connectable and non-connectable BLE advertisements.
BLUEZ_PASSIVE_OR_PATTERNS = [
    (0, AdvertisementDataType.FLAGS, b"\x02"),
    (0, AdvertisementDataType.FLAGS, b"\x06"),
    (0, AdvertisementDataType.FLAGS, b"\x1a"),
]
API_PORT = 6053
WEB_PORT: int | None = None


class BleakBluetoothProxy(BluetoothProxy):
    """Implement the proxy backend with Bleak's cross-platform API."""

    def __init__(self, *, bluez_adapter: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault(
            "feature_flags",
            int(
                BluetoothProxyFeature.PASSIVE_SCAN
                | BluetoothProxyFeature.ACTIVE_CONNECTIONS
                | BluetoothProxyFeature.REMOTE_CACHING
                | BluetoothProxyFeature.RAW_ADVERTISEMENTS
                | BluetoothProxyFeature.FEATURE_STATE_AND_MODE
            ),
        )
        kwargs.setdefault("active_scan", True)
        super().__init__(**kwargs)
        self._bluez_adapter = bluez_adapter
        self._clients: dict[int, BleakClient] = {}
        self._scanner: BleakScanner | None = None

    def _scanner_for_mode(
        self,
        active: bool,
        callback: Callable[[BLEDevice, AdvertisementData], None],
    ) -> BleakScanner:
        bluez: dict[str, Any] = {}
        if self._bluez_adapter is not None:
            bluez["adapter"] = self._bluez_adapter
        if not active:
            bluez["or_patterns"] = BLUEZ_PASSIVE_OR_PATTERNS
        return BleakScanner(
            detection_callback=callback,
            scanning_mode="active" if active else "passive",
            bluez=bluez,
        )

    async def start_scan(self, active: bool) -> None:
        def on_detection(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            address = bluetooth_address_to_int(device.address)
            asyncio.create_task(
                self.publish_advertisement(
                    BluetoothAdvertisement(
                        address=address,
                        rssi=advertisement_data.rssi,
                        address_type=_address_type(advertisement_data),
                        name=advertisement_data.local_name or device.name or "",
                        service_uuids=advertisement_data.service_uuids,
                        service_data=dict(advertisement_data.service_data),
                        manufacturer_data=dict(advertisement_data.manufacturer_data),
                    )
                )
            )

        scanner = self._scanner_for_mode(active, on_detection)
        self._scanner = scanner
        try:
            await scanner.start()
        except BleakError:
            if active:
                self._scanner = None
                raise
            logger.warning(
                "Passive BLE scanning is unavailable; falling back to active "
                "scanning. On Linux, enable BlueZ experimental features to "
                "use passive mode.",
                exc_info=True,
            )
            with suppress(Exception):
                await scanner.stop()
            scanner = self._scanner_for_mode(True, on_detection)
            self._scanner = scanner
            await scanner.start()
            self._set_actual_scan_mode(True)

    async def stop_scan(self) -> None:
        scanner, self._scanner = self._scanner, None
        if scanner is not None:
            await scanner.stop()

    async def _client(self, address: int) -> BleakClient:
        client = self._clients.get(address)
        if client is None or not client.is_connected:
            raise RuntimeError(f"not connected: {bluetooth_address_to_str(address)}")
        return client

    async def connect(self, address: int, address_type: int, use_cache: bool) -> int:
        del address_type, use_cache
        bluez = (
            {"adapter": self._bluez_adapter} if self._bluez_adapter is not None else {}
        )
        client = BleakClient(bluetooth_address_to_str(address), bluez=bluez)
        await client.connect()
        self._clients[address] = client
        return client.mtu_size

    async def disconnect(self, address: int) -> None:
        client = self._clients.pop(address, None)
        if client is not None:
            await client.disconnect()

    async def get_services(self, address: int) -> Sequence[BluetoothGATTService]:
        client = await self._client(address)
        services = []
        for service in client.services:
            characteristics = []
            for characteristic in service.characteristics:
                descriptors = [
                    BluetoothGATTDescriptor(descriptor.uuid, descriptor.handle)
                    for descriptor in characteristic.descriptors
                ]
                characteristics.append(
                    BluetoothGATTCharacteristic(
                        characteristic.uuid,
                        characteristic.handle,
                        _bleak_properties(characteristic.properties),
                        descriptors,
                    )
                )
            services.append(
                BluetoothGATTService(service.uuid, service.handle, characteristics)
            )
        return services

    async def read_characteristic(self, address: int, handle: int) -> bytes:
        return bytes(await (await self._client(address)).read_gatt_char(handle))

    async def write_characteristic(
        self, address: int, handle: int, data: bytes, response: bool
    ) -> None:
        await (await self._client(address)).write_gatt_char(
            handle, data, response=response
        )

    async def read_descriptor(self, address: int, handle: int) -> bytes:
        return bytes(await (await self._client(address)).read_gatt_descriptor(handle))

    async def write_descriptor(self, address: int, handle: int, data: bytes) -> None:
        await (await self._client(address)).write_gatt_descriptor(handle, data)

    async def set_notify(
        self,
        address: int,
        handle: int,
        enable: bool,
        callback: Callable[[bytes], Awaitable[None]],
    ) -> None:
        client = await self._client(address)
        if enable:
            await client.start_notify(
                handle, lambda _handle, data: asyncio.create_task(callback(bytes(data)))
            )
        else:
            await client.stop_notify(handle)


def _bleak_properties(properties: list[str]) -> int:
    """Map Bleak property names to ESPHome's bit field."""
    values = {
        "broadcast": 0x01,
        "read": 0x02,
        "write-without-response": 0x04,
        "write": 0x08,
        "notify": 0x10,
        "indicate": 0x20,
        "authenticated-signed-writes": 0x40,
    }
    result = 0
    for property_name in properties:
        result |= values.get(property_name, 0)
    return result


def _address_type(advertisement_data: AdvertisementData) -> int:
    """Map BlueZ's address type to the ESPHome public/random wire value."""
    if (
        not sys.platform.startswith("linux")
        or len(advertisement_data.platform_data) < 2
    ):
        return 0
    properties = advertisement_data.platform_data[1]
    if isinstance(properties, dict) and properties.get("AddressType") == "random":
        return 1
    return 0


def _bluez_adapter_mac(adapter: str | None) -> str | None:
    """Read a Linux BlueZ adapter address without adding another dependency."""
    if adapter is None or not sys.platform.startswith("linux"):
        return None
    try:
        address = (
            Path(f"/sys/class/bluetooth/{adapter}/address")
            .read_text(encoding="ascii")
            .strip()
        )
        if len(address.split(":")) != 6:
            return None
        bluetooth_address_to_int(address)
    except (OSError, ValueError):
        return None
    return address.upper()


def _stable_host_mac(label: str) -> str:
    """Derive a stable, locally administered MAC for non-radio identities."""
    host_id = str(uuid.getnode()).encode("ascii")
    if sys.platform.startswith("linux"):
        with suppress(OSError):
            host_id = Path("/etc/machine-id").read_bytes().strip() or host_id
    value = bytearray(
        hashlib.sha256(host_id + b":" + label.encode("utf-8")).digest()[:6]
    )
    value[0] = (value[0] | 0x02) & 0xFE
    return ":".join(f"{part:02X}" for part in value)


def build_device(*, bluez_adapter: str | None = None) -> Device:
    """Build the example device without starting the network servers."""
    if bluez_adapter is None and sys.platform.startswith("linux"):
        bluez_adapter = "hci0"
    bluetooth_mac_address = _bluez_adapter_mac(bluez_adapter) or _stable_host_mac(
        f"bluetooth:{bluez_adapter or 'default'}"
    )
    device = Device(
        name="bleak-bluetooth-proxy",
        friendly_name="Bleak Bluetooth Proxy",
        mac_address=_stable_host_mac("esphome:bleak-bluetooth-proxy"),
        bluetooth_proxy=BleakBluetoothProxy(
            bluez_adapter=bluez_adapter,
            bluetooth_mac_address=bluetooth_mac_address,
            max_connections=9,
        ),
    )
    device.add_entity(
        TextSensorEntity(
            name="IP address",
            object_id="ip_address",
            icon="mdi:ip-network",
            initial_state=device.get_ip_address(),
        )
    )
    return device


def _feature_names(feature_flags: int) -> str:
    names = [
        feature.name
        for feature in BluetoothProxyFeature
        if feature_flags & int(feature)
    ]
    return ", ".join(names) if names else "none"


def _print_startup_diagnostics(
    device: Device, *, api_port: int, web_port: int | None
) -> None:
    bluetooth_proxy = device.bluetooth_proxy
    if bluetooth_proxy is None:
        bluetooth_mac_address = "disabled"
        feature_flags = 0
    else:
        bluetooth_mac_address = bluetooth_proxy.bluetooth_mac_address
        feature_flags = bluetooth_proxy.feature_flags
    entities = ", ".join(
        f"{entity.DOMAIN}.{entity.object_id}={getattr(entity, '_state', '')}"
        for entity in device.entities
    )
    print(f"Using aioesphomeserver from: {aioesphomeserver.__file__}")
    print(
        f"Starting {device.name} on API port {api_port}, web port {web_port or 'disabled'}"
    )
    print(f"Device MAC: {device.mac_address}")
    print(
        f"Project: {device.project_name or '<none>'} {device.project_version or ''}".rstrip()
    )
    print(f"Bluetooth MAC: {bluetooth_mac_address}")
    print(f"Bluetooth feature flags: {feature_flags} ({_feature_names(feature_flags)})")
    print(f"Exposed entities: {entities or 'none'}")


async def main() -> None:
    device = build_device()
    _print_startup_diagnostics(device, api_port=API_PORT, web_port=WEB_PORT)
    await device.run(api_port=API_PORT, web_port=WEB_PORT)


if __name__ == "__main__":
    asyncio.run(main())
