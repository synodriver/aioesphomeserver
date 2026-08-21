"""Run a small ESPHome-compatible device."""

import asyncio

from aioesphomeserver import Device, SensorEntity, SwitchEntity


async def main() -> None:
    device = Device(
        name="python-esphome-device",
        friendly_name="Python ESPHome Device",
        mac_address="02:00:00:00:10:01",
        model="Python host",
        esphome_version="1145.1.4",
        project_name="aioesphomeserver.example",
        project_version="1.0.0",
    )
    device.add_entity(SwitchEntity(name="Desk lamp"))
    device.add_entity(
        SensorEntity(name="Temperature", unit_of_measurement="C", accuracy_decimals=1)
    )
    await device.run(api_port=6053, web_port=8080)


if __name__ == "__main__":
    asyncio.run(main())
