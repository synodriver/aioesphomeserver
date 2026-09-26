import asyncio
from unittest.mock import AsyncMock

import pytest
from aioesphomeapi import APIClient
from aioesphomeapi.model import (
    NumberInfo,
    NumberState,
    SelectInfo,
    SelectState,
    SensorState,
)

from aioesphomeserver import (
    Device,
    NativeApiServer,
    NumberEntity,
    SelectEntity,
    SensorEntity,
)
from examples.external_data_entities import update_temperature


class RecordingNumber(NumberEntity):
    def __init__(self):
        super().__init__(name="Limit", min_value=0, max_value=100, step=1)
        self.commands = []

    async def on_command(self, value):
        self.commands.append(value)
        await self.set_state(value)


class RecordingSelect(SelectEntity):
    def __init__(self):
        super().__init__(name="Mode", options=("auto", "eco"))
        self.commands = []

    async def on_command(self, value):
        self.commands.append(value)
        await self.set_state(value)


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def test_sensor_number_and_select_with_official_client():
    asyncio.run(_test_sensor_number_and_select_with_official_client())


async def _test_sensor_number_and_select_with_official_client():
    sensor = SensorEntity(name="External value")
    number = RecordingNumber()
    select = RecordingSelect()
    device = Device(
        name="External Data Test",
        mac_address="02:00:00:00:00:03",
    )
    device.add_entity(sensor)
    device.add_entity(number)
    device.add_entity(select)

    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient(
            "127.0.0.1",
            api.bound_port,
            keepalive=60,
            expected_name=device.name,
        )
        await client.connect(login=True)
        _info, entities, _services = await client.device_info_and_list_entities()

        number_info = next(
            entity for entity in entities if isinstance(entity, NumberInfo)
        )
        select_info = next(
            entity for entity in entities if isinstance(entity, SelectInfo)
        )
        assert select_info.options == ["auto", "eco"]

        states = []
        client.subscribe_states(states.append)
        await _wait_for(lambda: len(states) >= 3)

        await sensor.set_state(42.5)
        await _wait_for(
            lambda: any(
                isinstance(state, SensorState)
                and state.key == sensor.key
                and state.state == 42.5
                for state in states
            )
        )

        client.number_command(number_info.key, 75)
        await _wait_for(lambda: number.commands == [75])
        await _wait_for(
            lambda: any(
                isinstance(state, NumberState)
                and state.key == number.key
                and state.state == 75
                for state in states
            )
        )

        client.select_command(select_info.key, "eco")
        await _wait_for(lambda: select.commands == ["eco"])
        await _wait_for(
            lambda: any(
                isinstance(state, SelectState)
                and state.key == select.key
                and state.state == "eco"
                for state in states
            )
        )
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)


def test_select_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="at least one option"):
        SelectEntity(name="Empty", options=())

    with pytest.raises(ValueError, match="initial_state"):
        SelectEntity(name="Invalid", options=("auto",), initial_state="eco")


def test_external_temperature_clears_missing_state_after_first_read():
    async def run():
        sensor = SensorEntity(name="External temperature", missing_state=True)
        device = Device(name="external-source")
        device.add_entity(sensor)
        source = AsyncMock()
        source.read_temperature.return_value = 23.5
        task = asyncio.create_task(update_temperature(sensor, source))
        try:
            await _wait_for(lambda: not sensor.missing_state)
            state = await sensor.build_state_response()
            assert state.state == 23.5
            assert not state.missing_state
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_first_external_read_publishes_even_if_value_matches_default():
    async def run():
        sensor = SensorEntity(name="External temperature", missing_state=True)
        device = Device(name="external-source")
        device.add_entity(sensor)
        source = AsyncMock()
        source.read_temperature.return_value = 0.0
        published = []
        original_publish = device.publish

        async def record_publish(publisher, key, message):
            if key == "state_change":
                published.append(message)
            await original_publish(publisher, key, message)

        device.publish = record_publish
        task = asyncio.create_task(update_temperature(sensor, source))
        try:
            await _wait_for(lambda: bool(published))
            assert published[0].state == 0.0
            assert not published[0].missing_state
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
