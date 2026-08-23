"""Call Home Assistant services and fire events from a Python ESPHome device."""

from __future__ import annotations

import asyncio

from aioesphomeserver import ButtonEntity, Device


class NotifyButton(ButtonEntity):
    """Call a Home Assistant service when Home Assistant presses the button."""

    async def on_press(self) -> None:
        if self.device is None:
            raise RuntimeError("button is not attached to a device")
        print("button pushed")
        await self.device.call_homeassistant_service(
            "persistent_notification.create",
            data={
                "title": "aioesphomeserver",
                "message": "The device button was pressed",
            },
        )


async def publish_example_event(device: Device) -> None:
    await asyncio.sleep(5)
    while True:
        await device.fire_homeassistant_event(
            "esphome.aioesphomeserver_heartbeat",
            data={"source": device.name},
            data_template={"message": "Heartbeat from {{ source }}"},
            variables={"source": device.name},
        )
        await asyncio.sleep(60)


async def main() -> None:
    device = Device(
        name="homeassistant-actions-device",
        friendly_name="Home Assistant Actions Device",
        mac_address="02:00:00:00:10:07",
        model="Python Home Assistant action example",
        project_name="aioesphomeserver.homeassistant-actions",
        project_version="1.0.0",
    )
    device.add_entity(
        NotifyButton(
            name="Notify Home Assistant",
            object_id="notify_home_assistant",
        )
    )

    async with asyncio.TaskGroup() as tg:
        tg.create_task(publish_example_event(device))
        tg.create_task(device.run(api_port=6053, web_port=None))


if __name__ == "__main__":
    asyncio.run(main())
