import asyncio
from unittest.mock import AsyncMock, patch

from aioesphomeapi.api_pb2 import CameraImageResponse

from examples.camera import DEMO_JPEG
from examples.entity_showcase import ShowcaseCamera, build_device


EXPECTED_DOMAINS = {
    "alarm_control_panel",
    "binary_sensor",
    "button",
    "camera",
    "climate",
    "cover",
    "date",
    "datetime",
    "event",
    "fan",
    "infrared",
    "light",
    "lock",
    "media_player",
    "number",
    "radio_frequency",
    "select",
    "sensor",
    "siren",
    "switch",
    "text",
    "text_sensor",
    "time",
    "update",
    "valve",
    "water_heater",
}


def test_entity_showcase_builds_every_domain() -> None:
    async def run() -> None:
        device, _entities = build_device()

        assert {entity.DOMAIN for entity in device.entities} == EXPECTED_DOMAINS
        assert len(device.entities) == len(EXPECTED_DOMAINS)
        for entity in device.entities:
            assert await entity.build_list_entities_response() is not None
            await entity.build_state_response()

    asyncio.run(run())


def test_entity_showcase_camera_returns_a_jpeg() -> None:
    async def run() -> None:
        device, entities = build_device()
        camera = entities["camera"]
        assert isinstance(camera, ShowcaseCamera)

        publish = AsyncMock()
        with patch.object(device, "publish", publish):
            await camera.on_request(single=True, stream=False)

        messages = [call.args[2] for call in publish.await_args_list]
        assert all(isinstance(message, CameraImageResponse) for message in messages)
        assert b"".join(message.data for message in messages) == DEMO_JPEG
        assert messages[-1].done is True

    asyncio.run(run())
