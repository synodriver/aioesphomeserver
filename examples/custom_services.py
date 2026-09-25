"""Expose synchronous and asynchronous Python functions as ESPHome actions."""

from __future__ import annotations

import asyncio

from aioesphomeserver import Device, ServiceArgument, SupportsResponseType


class Application:
    """Replace these callbacks with the application's real operations."""

    def set_scene(self, scene: str, brightness: float) -> None:
        print(f"Set scene: {scene}, brightness={brightness:.2f}")

    async def notify(self, message: str) -> None:
        await asyncio.sleep(0.05)
        print(f"Notification: {message}")

    async def echo(self, value: str) -> dict[str, str]:
        return {"echo": value}


async def main() -> None:
    app = Application()
    device = Device(
        name="python-custom-services",
        friendly_name="Python Custom Services",
        mac_address="02:00:00:00:10:06",
        model="Python API actions example",
        project_name="aioesphomeserver.custom-services-example",
        project_version="1.0.0",
    )
    device.add_service(
        "set_scene",
        app.set_scene,
        description="Select a scene and set its brightness.",
        arguments={
            "scene": ServiceArgument(str, "Scene name", "evening"),
            "brightness": ServiceArgument(float, "Brightness from 0 to 1", "0.6"),
        },
    )
    device.add_service("notify", app.notify, arguments={"message": str})
    device.add_service(
        "echo",
        app.echo,
        arguments={"value": str},
        supports_response=SupportsResponseType.OPTIONAL,
        description="Return the supplied value in a JSON response.",
    )
    await device.run(api_port=6053, web_port=None)


if __name__ == "__main__":
    asyncio.run(main())
