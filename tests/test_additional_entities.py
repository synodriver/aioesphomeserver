import asyncio
import inspect

from aioesphomeapi import APIClient
from aioesphomeapi.model import (
    AlarmControlPanelCommand,
    AlarmControlPanelInfo,
    AlarmControlPanelState,
    ButtonInfo,
    CameraInfo,
    CoverInfo,
    DateInfo,
    DateTimeInfo,
    EventInfo,
    FanInfo,
    InfraredInfo,
    LockInfo,
    LockCommand,
    LockState,
    MediaPlayerCommand,
    MediaPlayerInfo,
    MediaPlayerState,
    NumberInfo,
    RadioFrequencyInfo,
    SelectInfo,
    SensorInfo,
    SirenInfo,
    TextInfo,
    TextSensorInfo,
    TimeInfo,
    UpdateInfo,
    ValveInfo,
    WaterHeaterInfo,
    WaterHeaterMode,
    WaterHeaterStateFlag,
)

from aioesphomeserver import (
    AlarmControlPanelEntity,
    ButtonEntity,
    CameraEntity,
    ClimateEntity,
    CoverEntity,
    DateEntity,
    DateTimeEntity,
    Device,
    EventEntity,
    FanEntity,
    InfraredEntity,
    LightEntity,
    LockEntity,
    MediaPlayerEntity,
    NativeApiServer,
    NumberEntity,
    RadioFrequencyEntity,
    SelectEntity,
    SirenEntity,
    SwitchEntity,
    TextEntity,
    TextSensorEntity,
    TimeEntity,
    UpdateEntity,
    ValveEntity,
    WaterHeaterEntity,
)


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def test_command_entities_expose_async_command_hooks():
    command_entities = (
        SwitchEntity,
        LightEntity,
        ClimateEntity,
        NumberEntity,
        SelectEntity,
        ButtonEntity,
        TextEntity,
        CoverEntity,
        FanEntity,
        LockEntity,
        MediaPlayerEntity,
        SirenEntity,
        ValveEntity,
        WaterHeaterEntity,
        AlarmControlPanelEntity,
        DateEntity,
        DateTimeEntity,
        TimeEntity,
        UpdateEntity,
        CameraEntity,
        InfraredEntity,
        RadioFrequencyEntity,
    )
    for entity_type in command_entities:
        assert inspect.iscoroutinefunction(entity_type.on_command), entity_type.__name__


def test_core_command_hooks_with_official_client():
    asyncio.run(_test_core_command_hooks_with_official_client())


async def _test_core_command_hooks_with_official_client():
    class RecordingSwitch(SwitchEntity):
        def __init__(self):
            super().__init__(name="Switch")
            self.commands = []

        async def on_command(self, value):
            self.commands.append(value)
            await super().on_command(value)

    class RecordingLight(LightEntity):
        def __init__(self):
            super().__init__(name="Light")
            self.commands = []

        async def on_command(self, command):
            self.commands.append(command)
            await super().on_command(command)

    class RecordingClimate(ClimateEntity):
        def __init__(self):
            super().__init__(name="Climate")
            self.commands = []

        async def on_command(self, command):
            self.commands.append(command)
            await super().on_command(command)

    switch, light, climate = RecordingSwitch(), RecordingLight(), RecordingClimate()
    device = Device(name="Commands", mac_address="02:00:00:00:00:06")
    for entity in (switch, light, climate):
        device.add_entity(entity)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        await client.device_info_and_list_entities()
        client.switch_command(switch.key, True)
        client.light_command(light.key, brightness=0.5)
        client.climate_command(climate.key, target_temperature=23.0)
        await _wait_for(
            lambda: bool(switch.commands and light.commands and climate.commands)
        )
        assert switch.commands == [True]
        assert light.commands[0].brightness == 0.5
        assert climate.commands[0].target_temperature == 23.0
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)


def test_command_enums_are_translated_to_entity_states():
    asyncio.run(_test_command_enums_are_translated_to_entity_states())


async def _test_command_enums_are_translated_to_entity_states():
    lock = LockEntity(name="Lock")
    media_player = MediaPlayerEntity(name="Media player")
    alarm = AlarmControlPanelEntity(name="Alarm")
    water_heater = WaterHeaterEntity(name="Water heater")
    device = Device(name="Command states", mac_address="02:00:00:00:00:07")
    for entity in (lock, media_player, alarm, water_heater):
        device.add_entity(entity)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        await client.device_info_and_list_entities()

        for command, state in (
            (LockCommand.UNLOCK, LockState.UNLOCKED),
            (LockCommand.LOCK, LockState.LOCKED),
            (LockCommand.OPEN, LockState.OPEN),
        ):
            client.lock_command(lock.key, command)
            await _wait_for(lambda state=state: lock.state == state)

        for command, state in (
            (MediaPlayerCommand.PLAY, MediaPlayerState.PLAYING),
            (MediaPlayerCommand.PAUSE, MediaPlayerState.PAUSED),
            (MediaPlayerCommand.STOP, MediaPlayerState.IDLE),
            (MediaPlayerCommand.TURN_ON, MediaPlayerState.ON),
            (MediaPlayerCommand.TURN_OFF, MediaPlayerState.OFF),
        ):
            client.media_player_command(media_player.key, command=command)
            await _wait_for(lambda state=state: media_player.state == state)
        client.media_player_command(
            media_player.key, command=MediaPlayerCommand.MUTE, volume=0.25
        )
        await _wait_for(lambda: media_player.muted and media_player.volume == 0.25)
        client.media_player_command(
            media_player.key, command=MediaPlayerCommand.UNMUTE
        )
        await _wait_for(lambda: not media_player.muted)

        for command, state in (
            (AlarmControlPanelCommand.ARM_AWAY, AlarmControlPanelState.ARMED_AWAY),
            (AlarmControlPanelCommand.ARM_HOME, AlarmControlPanelState.ARMED_HOME),
            (AlarmControlPanelCommand.ARM_NIGHT, AlarmControlPanelState.ARMED_NIGHT),
            (
                AlarmControlPanelCommand.ARM_VACATION,
                AlarmControlPanelState.ARMED_VACATION,
            ),
            (
                AlarmControlPanelCommand.ARM_CUSTOM_BYPASS,
                AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
            ),
            (AlarmControlPanelCommand.TRIGGER, AlarmControlPanelState.TRIGGERED),
            (AlarmControlPanelCommand.DISARM, AlarmControlPanelState.DISARMED),
        ):
            client.alarm_control_panel_command(alarm.key, command)
            await _wait_for(lambda state=state: alarm.state == state)

        client.water_heater_command(
            water_heater.key,
            mode=WaterHeaterMode.ECO,
            target_temperature=50.0,
            target_temperature_low=45.0,
            target_temperature_high=55.0,
            away=True,
            on=True,
        )
        expected_flags = WaterHeaterStateFlag.AWAY | WaterHeaterStateFlag.ON
        await _wait_for(
            lambda: water_heater.mode == WaterHeaterMode.ECO
            and water_heater.target_temperature == 50.0
            and water_heater.target_temperature_low == 45.0
            and water_heater.target_temperature_high == 55.0
            and water_heater.state == expected_flags
        )
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)


def test_all_missing_entity_types_are_discoverable():
    asyncio.run(_test_all_missing_entity_types_are_discoverable())


async def _test_all_missing_entity_types_are_discoverable():
    entities = [
        ButtonEntity(name="Button"),
        TextSensorEntity(name="Text sensor"),
        TextEntity(name="Text", max_length=50),
        CoverEntity(name="Cover"),
        FanEntity(name="Fan"),
        LockEntity(name="Lock"),
        MediaPlayerEntity(name="Media player"),
        SirenEntity(name="Siren"),
        ValveEntity(name="Valve"),
        WaterHeaterEntity(name="Water heater"),
        AlarmControlPanelEntity(name="Alarm"),
        DateEntity(name="Date"),
        DateTimeEntity(name="Date time"),
        TimeEntity(name="Time"),
        UpdateEntity(name="Update"),
        EventEntity(name="Event", event_types=("pressed",)),
        CameraEntity(name="Camera"),
        InfraredEntity(name="Infrared"),
        RadioFrequencyEntity(name="Radio"),
    ]
    device = Device(name="All entities", mac_address="02:00:00:00:00:04")
    for entity in entities:
        device.add_entity(entity)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        _info, discovered, _services = await client.device_info_and_list_entities()
        info_types = {type(info) for info in discovered}
        assert {
            ButtonInfo,
            TextSensorInfo,
            TextInfo,
            CoverInfo,
            FanInfo,
            LockInfo,
            MediaPlayerInfo,
            SirenInfo,
            ValveInfo,
            WaterHeaterInfo,
            AlarmControlPanelInfo,
            DateInfo,
            DateTimeInfo,
            TimeInfo,
            UpdateInfo,
            EventInfo,
            CameraInfo,
            InfraredInfo,
            RadioFrequencyInfo,
        } <= info_types
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)


def test_event_and_text_hooks_publish_state():
    asyncio.run(_test_event_and_text_hooks_publish_state())


async def _test_event_and_text_hooks_publish_state():
    text_sensor = TextSensorEntity(name="Text sensor")
    event = EventEntity(name="Event", event_types=("ready",))
    device = Device(name="Hooks", mac_address="02:00:00:00:00:05")
    device.add_entity(text_sensor)
    device.add_entity(event)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        _info, _entities, _services = await client.device_info_and_list_entities()
        states = []
        client.subscribe_states(states.append)
        await text_sensor.set_state("ready")
        await event.trigger("ready")
        await _wait_for(
            lambda: any(getattr(state, "state", None) == "ready" for state in states)
        )
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)
