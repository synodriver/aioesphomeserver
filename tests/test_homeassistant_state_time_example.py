import asyncio
from unittest.mock import AsyncMock, patch

from aioesphomeapi import APIClient

from aioesphomeserver import NativeApiServer
from examples.homeassistant_state_time import build_device


async def wait_for(predicate) -> None:
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.01)


def test_example_registers_state_before_device_start() -> None:
    asyncio.run(_test_example_registers_state_before_device_start())


async def _test_example_registers_state_before_device_start() -> None:
    device = await build_device()
    assert not any(isinstance(entity, NativeApiServer) for entity in device.entities)
    with patch.object(device, "register_zeroconf", AsyncMock(return_value=None)):
        task = asyncio.create_task(device.run(api_port=0, web_port=None))
        client = None
        try:
            await wait_for(lambda: any(
                isinstance(entity, NativeApiServer) and entity.bound_port is not None
                for entity in device.entities
            ))
            server = next(
                entity for entity in device.entities
                if isinstance(entity, NativeApiServer)
            )
            assert server.bound_port is not None
            client = APIClient("127.0.0.1", server.bound_port, keepalive=60)
            await client.connect()
            subscriptions: list[tuple[str, str | None]] = []
            client.subscribe_home_assistant_states(
                lambda entity_id, attribute: subscriptions.append((entity_id, attribute))
            )
            await wait_for(lambda: bool(subscriptions))
            assert subscriptions == [("sensor.outdoor_temperature", "")]
        finally:
            if client is not None:
                await client.disconnect()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
