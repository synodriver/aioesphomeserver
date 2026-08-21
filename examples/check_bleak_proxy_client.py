"""Check what Home Assistant should see from examples/bleak_proxy.py.

Run the proxy first, then run this script from the same Python environment:

    python examples/check_bleak_proxy_client.py 127.0.0.1 6053
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothProxyFeature


def _feature_names(feature_flags: int) -> str:
    names = [
        feature.name
        for feature in BluetoothProxyFeature
        if feature_flags & int(feature)
    ]
    return ", ".join(names) if names else "none"


async def _check(host: str, port: int) -> int:
    client = APIClient(host, port, keepalive=60)
    try:
        async with asyncio.timeout(10):
            await client.connect()
            device_info, entities, services = (
                await client.device_info_and_list_entities()
            )
        api_version = client.api_version
        feature_flags = device_info.bluetooth_proxy_feature_flags_compat(api_version)

        print(f"API version: {api_version}")
        print(f"Device name: {device_info.name}")
        print(f"Device MAC: {device_info.mac_address}")
        print(f"ESPHome version: {device_info.esphome_version}")
        print(f"Manufacturer: {device_info.manufacturer}")
        print(f"Model: {device_info.model}")
        print(
            f"Project: {device_info.project_name or '<none>'} {device_info.project_version or ''}".rstrip()
        )
        print(f"Web server port: {device_info.webserver_port}")
        print(
            f"Bluetooth MAC: {device_info.bluetooth_mac_address or device_info.mac_address}"
        )
        print(
            f"Bluetooth feature flags: {feature_flags} ({_feature_names(feature_flags)})"
        )
        print(f"Entity count: {len(entities)}")
        for entity in entities:
            print(
                f"- {type(entity).__name__}: "
                f"key={entity.key} object_id={entity.object_id!r} name={entity.name!r}"
            )
        print(f"Service count: {len(services)}")

        if not feature_flags:
            print("ERROR: device did not advertise Bluetooth proxy feature flags")
            return 2
        if not entities:
            print("ERROR: device returned no entities")
            return 3
        return 0
    finally:
        with suppress(Exception):
            await client.disconnect(force=True)


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6053
    return asyncio.run(_check(host, port))


if __name__ == "__main__":
    raise SystemExit(main())
