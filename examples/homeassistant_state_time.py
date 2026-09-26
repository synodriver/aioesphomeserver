"""Subscribe to a Home Assistant state and receive its time response."""

from __future__ import annotations

import asyncio
from typing import Any

from aioesphomeapi.api_pb2 import GetTimeResponse, HomeAssistantStateResponse

from aioesphomeserver import Device
from aioesphomeserver.basic_entity import BasicEntity


class HomeAssistantInput(BasicEntity):
    async def handle(self, key: str, message: Any) -> None:
        if key == "homeassistant_state" and isinstance(message, HomeAssistantStateResponse):
            print(f"{message.entity_id}: {message.state}")
        elif key == "time_response" and isinstance(message, GetTimeResponse):
            print(f"Epoch: {message.epoch_seconds}")
            if message.HasField("parsed_timezone"):
                print(f"UTC offset: {message.parsed_timezone.std_offset_seconds}")


async def request_time_periodically(device: Device) -> None:
    while True:
        await asyncio.sleep(30)
        await device.request_time()


async def build_device() -> Device:
    device = Device(
        name="homeassistant-input",
        project_name="aioesphomeserver.homeassistant-input",
    )
    device.add_entity(HomeAssistantInput("_input"))
    await device.subscribe_homeassistant_state("sensor.outdoor_temperature")
    return device


async def main() -> None:
    device = await build_device()
    async with asyncio.TaskGroup() as group:
        group.create_task(device.run(api_port=6053, web_port=None))
        group.create_task(request_time_periodically(device))


if __name__ == "__main__":
    asyncio.run(main())
