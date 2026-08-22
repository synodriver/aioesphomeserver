"""Expose a snapshot and JPEG stream through the ESPHome camera protocol."""

from __future__ import annotations

import asyncio
import base64

from aioesphomeserver import CameraEntity, Device

# A small valid JPEG keeps this example runnable without a camera. Replace
# capture_frame() with an application-specific camera backend in production.
DEMO_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAwAEADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAT/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCPAVJgAAAAAAAAAAAAAAAAAAAAAH//2Q=="
)
CAMERA_STREAM_DURATION = 5.0


class ExampleCamera(CameraEntity):
    """Bridge an application camera into ESPHome snapshot/stream requests."""

    def __init__(
        self,
        *,
        name: str = "Camera",
        object_id: str = "camera",
        icon: str = "mdi:camera",
    ) -> None:
        super().__init__(name=name, object_id=object_id, icon=icon)
        self._stream_task: asyncio.Task[None] | None = None

    async def capture_frame(self) -> bytes:
        """Return one complete JPEG frame from the application camera."""
        return DEMO_JPEG

    async def on_request(self, single: bool, stream: bool) -> None:
        if single:
            await self.send_image(await self.capture_frame())
        if stream and self._stream_task is None:
            self._stream_task = asyncio.create_task(self._stream_frames())

    async def _stream_frames(self) -> None:
        try:
            async with asyncio.timeout(CAMERA_STREAM_DURATION):
                while True:
                    await self.send_image(await self.capture_frame())
                    await asyncio.sleep(0.2)
        except TimeoutError:
            pass
        finally:
            self._stream_task = None

    async def stop(self) -> None:
        """Stop the stream when Device.run() is shutting down."""
        if self._stream_task is not None:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
            self._stream_task = None


async def main() -> None:
    camera = ExampleCamera()
    device = Device(
        name="python-camera-device",
        friendly_name="Python Camera Device",
        mac_address="02:00:00:00:10:05",
        model="Python camera example",
        project_name="aioesphomeserver.camera-example",
        project_version="1.0.0",
    )
    device.add_entity(camera)
    await device.run(api_port=6053, web_port=None)


if __name__ == "__main__":
    asyncio.run(main())
