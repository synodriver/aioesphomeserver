import asyncio
from typing import Any

from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import (
    AlarmControlPanelCommandRequest,
    AreaInfo,
    CameraImageRequest,
    CoverCommandRequest,
    DeviceInfo,
    GetTimeResponse,
    HelloRequest,
    HomeAssistantStateResponse,
    LockCommandRequest,
    NoiseEncryptionSetKeyRequest,
)
from aioesphomeapi.model import LogLevel
from aioesphomeapi.model import (
    AlarmControlPanelCommand, AlarmControlPanelState,
    LegacyCoverCommand, LegacyCoverState, LockCommand, LockState,
)

from aioesphomeserver import AlarmControlPanelEntity, CameraEntity, ClimateEntity, CoverEntity, Device, LockEntity, NativeApiServer, SwitchEntity, WaterHeaterEntity
from aioesphomeserver.basic_entity import BasicEntity
from aioesphomeserver.native_api_server import NativeApiConnection


async def wait_for(predicate: Any) -> None:
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.01)


def test_cover_legacy_commands_and_camera_request() -> None:
    asyncio.run(_test_cover_legacy_commands_and_camera_request())


async def _test_cover_legacy_commands_and_camera_request() -> None:
    class Camera(CameraEntity):
        def __init__(self) -> None:
            super().__init__(name="Camera")
            self.requests: list[tuple[bool, bool]] = []

        async def on_request(self, single: bool, stream: bool) -> None:
            self.requests.append((single, stream))

    device = Device(name="fields")
    cover = CoverEntity(name="Cover")
    camera = Camera()
    device.add_entity(cover)
    device.add_entity(camera)
    assert (await cover.build_state_response()).legacy_state == LegacyCoverState.CLOSED
    for legacy, position in (
        (LegacyCoverCommand.OPEN, 1.0),
        (LegacyCoverCommand.CLOSE, 0.0),
    ):
        command = CoverCommandRequest(
            key=cover.key, has_legacy_command=True, legacy_command=legacy
        )
        await cover.on_command(command)
        assert cover.position == position
        assert not command.stop
    await cover.on_command(CoverCommandRequest(
        key=cover.key, has_position=True, position=0.5,
        has_legacy_command=True, legacy_command=LegacyCoverCommand.CLOSE,
    ))
    assert cover.position == 0.5
    await camera.handle("client_request", CameraImageRequest(single=True))
    assert camera.requests == [(True, False)]


def test_device_info_and_new_missing_state_fields() -> None:
    asyncio.run(_test_device_info_and_new_missing_state_fields())


async def _test_device_info_and_new_missing_state_fields() -> None:
    device = Device(
        name="multi", suggested_area="Fallback",
        area=AreaInfo(area_id=2, name="Actual"),
        areas=[AreaInfo(area_id=2, name="Actual")],
        devices=[DeviceInfo(device_id=7, name="Subdevice", area_id=2)],
        compilation_time="today", has_deep_sleep=True,
    )
    info = await device.build_device_info_response()
    assert info.area.name == "Actual"
    assert info.devices[0].device_id == 7
    assert info.areas[0].area_id == 2
    assert info.compilation_time == "today" and info.has_deep_sleep
    for entity in (
        SwitchEntity(name="Switch", device_id=7, missing_state=True),
        ClimateEntity(name="Climate", device_id=7, missing_state=True),
        WaterHeaterEntity(name="Heater", device_id=7, missing_state=True),
    ):
        device.add_entity(entity)
        assert (await entity.build_list_entities_response()).device_id == 7
        state = await entity.build_state_response()
        assert state.device_id == 7 and state.missing_state


def test_homeassistant_subscription_and_time_with_official_client() -> None:
    asyncio.run(_test_homeassistant_subscription_and_time_with_official_client())


async def _test_homeassistant_subscription_and_time_with_official_client() -> None:
    class Recorder(BasicEntity):
        def __init__(self) -> None:
            super().__init__("_recorder")
            self.states: list[HomeAssistantStateResponse] = []
            self.times: list[GetTimeResponse] = []

        async def handle(self, key: str, message: Any) -> None:
            if key == "homeassistant_state":
                self.states.append(message)
            elif key == "time_response":
                self.times.append(message)

    device = Device(name="subscriptions")
    recorder = Recorder()
    device.add_entity(recorder)
    api = NativeApiServer(name="_api", host="127.0.0.1", port=0)
    device.add_entity(api)
    await device.subscribe_homeassistant_state("sensor.room", "temperature")
    await device.subscribe_homeassistant_state("sensor.once", once=True)
    task = asyncio.create_task(api.run())
    client = None
    try:
        await wait_for(lambda: api.bound_port is not None)
        assert api.bound_port is not None
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        subscriptions: list[tuple[str, str | None]] = []
        requests: list[tuple[str, str | None]] = []
        client.subscribe_home_assistant_states(
            lambda entity, attr: subscriptions.append((entity, attr)),
            lambda entity, attr: requests.append((entity, attr)),
        )
        await wait_for(lambda: len(subscriptions) == 1 and len(requests) == 1)
        assert subscriptions == [("sensor.room", "temperature")]
        assert requests == [("sensor.once", "")]
        client.send_home_assistant_state("sensor.room", "temperature", "24")
        client.send_home_assistant_state("sensor.once", "", "ready")
        client.send_home_assistant_state("sensor.other", "", "ignored")
        await wait_for(lambda: len(recorder.states) == 2)
        assert {message.state for message in recorder.states} == {"24", "ready"}
        client.send_home_assistant_state("sensor.once", "", "ignored")
        await asyncio.sleep(0.05)
        assert len(recorder.states) == 2
        await device.request_time()
        await wait_for(lambda: bool(recorder.times))
        assert recorder.times[0].epoch_seconds > 0
        await device.subscribe_homeassistant_state("sensor.new")
        await wait_for(lambda: len(subscriptions) == 2)
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_noise_key_request_is_rejected_without_provisioning() -> None:
    asyncio.run(_test_noise_key_request_is_rejected_without_provisioning())


async def _test_noise_key_request_is_rejected_without_provisioning() -> None:
    class Client:
        def __init__(self) -> None:
            self.responses: list[Any] = []

        async def write_message(self, message: Any) -> None:
            self.responses.append(message)

    device = Device(name="fixed-key")
    api = NativeApiServer(name="_api")
    device.add_entity(api)
    client = Client()
    await api.handle_noise_key_request(client, NoiseEncryptionSetKeyRequest(key=b"a" * 32))  # type: ignore[arg-type]
    assert client.responses[0].success is False
    assert device.encryption_key is None


def test_required_alarm_and_lock_codes() -> None:
    asyncio.run(_test_required_alarm_and_lock_codes())


async def _test_required_alarm_and_lock_codes() -> None:
    device = Device(name="codes")
    alarm = AlarmControlPanelEntity(
        name="Alarm", requires_code=True, requires_code_to_arm=True, code="1234"
    )
    lock = LockEntity(name="Lock", code="1234")
    lock.requires_code = True
    device.add_entity(alarm)
    device.add_entity(lock)
    await alarm.on_command(AlarmControlPanelCommandRequest(
        command=AlarmControlPanelCommand.ARM_AWAY, code="wrong"
    ))
    assert alarm.state != AlarmControlPanelState.ARMED_AWAY
    await alarm.on_command(AlarmControlPanelCommandRequest(
        command=AlarmControlPanelCommand.ARM_AWAY, code="1234"
    ))
    assert alarm.state == AlarmControlPanelState.ARMED_AWAY
    await alarm.on_command(AlarmControlPanelCommandRequest(
        command=AlarmControlPanelCommand.DISARM, code="wrong"
    ))
    assert alarm.state == AlarmControlPanelState.ARMED_AWAY
    await lock.on_command(LockCommandRequest(
        command=LockCommand.UNLOCK, has_code=True, code="wrong"
    ))
    assert lock.state != LockState.UNLOCKED
    await lock.on_command(LockCommandRequest(
        command=LockCommand.UNLOCK, has_code=True, code="1234"
    ))
    assert lock.state == LockState.UNLOCKED


def test_hello_rejects_unsupported_outgoing_target() -> None:
    asyncio.run(_test_hello_rejects_unsupported_outgoing_target())


async def _test_hello_rejects_unsupported_outgoing_target() -> None:
    device = Device(name="inbound-only")
    api = NativeApiServer(name="_api")
    device.add_entity(api)
    connection = NativeApiConnection(api, asyncio.StreamReader(), None)  # type: ignore[arg-type]
    await connection.handle_message(HelloRequest(
        client_info="outgoing client", outgoing_connection_target=True
    ))
    assert connection.client_info == "outgoing client"
    assert not connection.running


def test_log_level_and_dump_config_with_official_client() -> None:
    asyncio.run(_test_log_level_and_dump_config_with_official_client())


async def _test_log_level_and_dump_config_with_official_client() -> None:
    class ConfigDevice(Device):
        async def dump_config(self, client: Any) -> None:
            await client.log(3, "safe config summary")

    device = ConfigDevice(name="logs")
    api = NativeApiServer(name="_api", host="127.0.0.1", port=0)
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    client = None
    try:
        await wait_for(lambda: api.bound_port is not None)
        assert api.bound_port is not None
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        logs: list[Any] = []
        client.subscribe_logs(logs.append, log_level=LogLevel.LOG_LEVEL_INFO, dump_config=True)
        await wait_for(lambda: len(logs) == 1)
        assert logs[0].message == b"safe config summary"
        await device.publish(None, "log", (4, "debug hidden"))
        await asyncio.sleep(0.05)
        assert len(logs) == 1
        await device.publish(None, "log", (2, "warning visible"))
        await wait_for(lambda: len(logs) == 2)
        client.subscribe_logs(logs.append, log_level=LogLevel.LOG_LEVEL_NONE)
        await wait_for(lambda: any(c.log_level == 0 for c in api._clients))
        await device.publish(None, "log", (2, "ignored"))
        await asyncio.sleep(0.05)
        assert all(message.message != b"ignored" for message in logs)
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
