import asyncio
from unittest.mock import AsyncMock, patch

from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import CameraImageResponse

from aioesphomeserver import NativeApiServer
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
        device, entities = build_device()

        assert {entity.DOMAIN for entity in device.entities} == EXPECTED_DOMAINS
        assert len(device.entities) == len(EXPECTED_DOMAINS)
        info = await device.build_device_info_response()
        assert info.area.name == "Office"
        assert info.devices[0].device_id == 1
        assert info.areas[0].area_id == 1
        climate = await entities["climate"].build_list_entities_response()
        assert climate is not None
        assert climate.supported_custom_fan_modes == ["silent"]
        assert climate.supported_custom_presets == ["boost"]
        light = await entities["light"].build_list_entities_response()
        assert light is not None
        assert (light.min_mireds, light.max_mireds) == (153.0, 500.0)
        sensor = await entities["sensor"].build_list_entities_response()
        assert sensor is not None
        assert sensor.device_id == 1
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


def test_official_client_discovers_showcase_subdevice() -> None:
    async def run() -> None:
        device, _entities = build_device()
        api = NativeApiServer(name="_api", host="127.0.0.1", port=0)
        device.add_entity(api)
        task = asyncio.create_task(api.run())
        client = None
        try:
            async with asyncio.timeout(4):
                while api.bound_port is None:
                    await asyncio.sleep(0.01)
            client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
            await client.connect()
            info, entities, _services = await client.device_info_and_list_entities()
            assert len(entities) == len(EXPECTED_DOMAINS)
            assert info.devices[0].device_id == 1
        finally:
            if client is not None:
                await client.disconnect()
            await api.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
