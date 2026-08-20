import asyncio

from aioesphomeapi.api_pb2 import CameraImageResponse

from examples.camera import DEMO_JPEG, ExampleCamera


class _FakeDevice:
    def __init__(self) -> None:
        self.messages = []

    async def publish(self, _publisher, _key, message) -> None:
        self.messages.append(message)


def test_camera_example_returns_a_snapshot():
    async def run() -> None:
        device = _FakeDevice()
        camera = ExampleCamera()
        camera.device = device
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
        camera.device = device
        camera.key = 8

        await camera.on_request(single=False, stream=True)
        await asyncio.sleep(0)
        assert camera._stream_task is not None
        await camera.stop()
        assert camera._stream_task is None
        assert device.messages

    asyncio.run(run())
