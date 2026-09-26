"""Expose an external data source as Sensor, Number, and Select entities."""

from __future__ import annotations

import asyncio
import random

from aioesphomeapi.model import EntityCategory, NumberMode, SensorStateClass

from aioesphomeserver import Device, NumberEntity, SelectEntity, SensorEntity


class ExternalDataSource:
    """Replace these methods with HTTP, database, serial, or SDK calls."""

    async def read_temperature(self) -> float:
        await asyncio.sleep(0.05)
        return 20.0 + random.random() * 5.0

    async def set_target_temperature(self, value: float) -> None:
        await asyncio.sleep(0.05)
        print(f"External operation: target temperature = {value:.1f} C")

    async def set_operating_mode(self, value: str) -> None:
        await asyncio.sleep(0.05)
        print(f"External operation: operating mode = {value}")


class TargetTemperatureNumber(NumberEntity):
    def __init__(self, source: ExternalDataSource) -> None:
        super().__init__(
            name="Target temperature",
            object_id="target_temperature",
            min_value=16.0,
            max_value=30.0,
            step=0.5,
            unit_of_measurement="C",
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
        )
        self.source = source
        self._state = 22.0

    async def on_command(self, value: float) -> None:
        await self.source.set_target_temperature(value)
        await self.set_state(value)


class OperatingModeSelect(SelectEntity):
    def __init__(self, source: ExternalDataSource) -> None:
        super().__init__(
            name="Operating mode",
            object_id="operating_mode",
            options=("auto", "comfort", "eco", "off"),
            initial_state="auto",
            entity_category=EntityCategory.CONFIG,
        )
        self.source = source

    async def on_command(self, value: str) -> None:
        await self.source.set_operating_mode(value)
        await self.set_state(value)


async def update_temperature(sensor: SensorEntity, source: ExternalDataSource) -> None:
    while True:
        value = await source.read_temperature()
        was_missing = sensor.missing_state
        previous_value = await sensor.get_state()
        sensor.missing_state = False
        await sensor.set_state(value)
        if was_missing and value == previous_value:
            await sensor.notify_state_change()
        await asyncio.sleep(10)


async def main() -> None:
    source = ExternalDataSource()
    temperature = SensorEntity(
        name="External temperature",
        object_id="external_temperature",
        missing_state=True,
        unit_of_measurement="C",
        accuracy_decimals=1,
        state_class=SensorStateClass.MEASUREMENT,
    )

    device = Device(
        name="external-data-device",
        friendly_name="External Data Device",
        mac_address="02:00:00:00:10:04",
        model="Python external data adapter",
        project_name="aioesphomeserver.external-data-example",
        project_version="1.0.0",
        encryption_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    )
    device.add_entity(temperature)
    device.add_entity(TargetTemperatureNumber(source))
    device.add_entity(OperatingModeSelect(source))

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(update_temperature(temperature, source))
        tasks.create_task(device.run(api_port=6053, web_port=None))


if __name__ == "__main__":
    asyncio.run(main())
