import asyncio
from typing import Any, cast
from unittest.mock import patch

from aioesphomeapi.api_pb2 import CameraImageResponse

from aioesphomeserver import CameraEntity
from examples.camera import DEMO_JPEG, ExampleCamera


class _FakeDevice:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def publish(self, _publisher, _key, message) -> None:
        self.messages.append(message)


def test_camera_example_returns_a_snapshot():
    async def run() -> None:
        device = _FakeDevice()
        camera = ExampleCamera()
        camera.device = cast(Any, device)
        camera.key = 7

        await camera.on_request(single=True, stream=False)

        assert len(device.messages) == 1
        response = device.messages[0]
        assert isinstance(response, CameraImageResponse)
        assert response.key == 7
        assert response.data == DEMO_JPEG
        assert response.done is True

    asyncio.run(run())


def test_camera_example_stops_stream_task():
    async def run() -> None:
        device = _FakeDevice()
        camera = ExampleCamera()
        camera.device = cast(Any, device)
        camera.key = 8

        await camera.on_request(single=False, stream=True)
        await asyncio.sleep(0)
        assert camera._stream_task is not None
        await camera.stop()
        assert camera._stream_task is None
        assert device.messages

    asyncio.run(run())


def test_camera_images_are_split_into_esphome_sized_chunks():
    async def run() -> None:
        device = _FakeDevice()
        camera = CameraEntity(name="Camera")
        camera.device = cast(Any, device)
        camera.key = 9
        image = bytes(range(256)) * 12

        await camera.send_image(image)

        assert [len(message.data) for message in device.messages] == [1390, 1390, 292]
        assert [message.done for message in device.messages] == [False, False, True]
        assert b"".join(message.data for message in device.messages) == image

    asyncio.run(run())


def test_camera_example_stream_stops_after_esphome_timeout():
    async def run() -> None:
        device = _FakeDevice()
        camera = ExampleCamera()
        camera.device = cast(Any, device)
        camera.key = 10

        with patch("examples.camera.CAMERA_STREAM_DURATION", 0.01):
            await camera.on_request(single=False, stream=True)
            async with asyncio.timeout(1):
                while camera._stream_task is not None:
                    await asyncio.sleep(0)

        assert device.messages

    asyncio.run(run())
