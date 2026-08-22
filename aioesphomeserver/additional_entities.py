"""ESPHome entity types not covered by the small core entity modules."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from aioesphomeapi.api_pb2 import (  # type: ignore
    AlarmControlPanelCommandRequest,
    AlarmControlPanelStateResponse,
    ButtonCommandRequest,
    CameraImageRequest,
    CameraImageResponse,
    CoverCommandRequest,
    CoverStateResponse,
    DateCommandRequest,
    DateStateResponse,
    DateTimeCommandRequest,
    DateTimeStateResponse,
    EventResponse,
    FanCommandRequest,
    FanStateResponse,
    InfraredRFReceiveEvent,
    InfraredRFTransmitRawTimingsRequest,
    ListEntitiesAlarmControlPanelResponse,
    ListEntitiesButtonResponse,
    ListEntitiesCameraResponse,
    ListEntitiesCoverResponse,
    ListEntitiesDateResponse,
    ListEntitiesDateTimeResponse,
    ListEntitiesEventResponse,
    ListEntitiesFanResponse,
    ListEntitiesInfraredResponse,
    ListEntitiesLockResponse,
    ListEntitiesMediaPlayerResponse,
    ListEntitiesRadioFrequencyResponse,
    ListEntitiesSirenResponse,
    ListEntitiesTextResponse,
    ListEntitiesTextSensorResponse,
    ListEntitiesTimeResponse,
    ListEntitiesUpdateResponse,
    ListEntitiesValveResponse,
    ListEntitiesWaterHeaterResponse,
    LockCommandRequest,
    LockStateResponse,
    MediaPlayerCommandRequest,
    MediaPlayerStateResponse,
    SelectCommandRequest,
    SirenCommandRequest,
    SirenStateResponse,
    TextCommandRequest,
    TextSensorStateResponse,
    TextStateResponse,
    TimeCommandRequest,
    TimeStateResponse,
    UpdateCommandRequest,
    UpdateStateResponse,
    ValveCommandRequest,
    ValveStateResponse,
    WaterHeaterCommandRequest,
    WaterHeaterStateResponse,
)
from aioesphomeapi.model import (  # type: ignore
    AlarmControlPanelCommand,
    AlarmControlPanelState,
    LockCommand,
    LockState,
    MediaPlayerCommand,
    MediaPlayerState,
    WaterHeaterCommandField,
    WaterHeaterStateFlag,
)

from .basic_entity import BasicEntity

CAMERA_IMAGE_CHUNK_SIZE = 1390


class _StateEntity(BasicEntity):
    async def _publish_state(self) -> None:
        await self.notify_state_change()

    async def state_json(self) -> str:
        return json.dumps(
            {"id": self.json_id, "name": self.name, "state": await self.get_state()}
        )


class ButtonEntity(BasicEntity):
    DOMAIN = "button"

    async def build_list_entities_response(self) -> ListEntitiesButtonResponse:
        return ListEntitiesButtonResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            disabled_by_default=bool(getattr(self, "disabled_by_default", False)),
            entity_category=self.entity_category,
            device_class=self.device_class or "",
        )

    async def on_press(self) -> None:
        """Override to execute the application action."""

    async def on_command(self) -> None:
        """Handle a button command requested by Home Assistant."""
        await self.on_press()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is ButtonCommandRequest and message.key == self.key:
            await self.on_command()


class TextSensorEntity(_StateEntity):
    DOMAIN = "text_sensor"

    def __init__(self, *args: Any, initial_state: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._state = str(initial_state)

    async def build_list_entities_response(self) -> ListEntitiesTextSensorResponse:
        return ListEntitiesTextSensorResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            disabled_by_default=bool(getattr(self, "disabled_by_default", False)),
            entity_category=self.entity_category,
            device_class=self.device_class or "",
        )

    async def build_state_response(self) -> TextSensorStateResponse:
        return TextSensorStateResponse(key=self.key, state=await self.get_state())

    async def get_state(self) -> str:
        return self._state

    async def set_state(self, value: str) -> None:
        value = str(value)
        changed = value != self._state
        self._state = value
        if changed:
            await self._publish_state()


class TextEntity(_StateEntity):
    DOMAIN = "text"

    def __init__(
        self,
        *args: Any,
        min_length: int = 0,
        max_length: int = 255,
        pattern: str = "",
        mode: int = 0,
        initial_state: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.min_length, self.max_length, self.pattern, self.mode = (
            min_length,
            max_length,
            pattern,
            mode,
        )
        self._state = str(initial_state)

    async def build_list_entities_response(self) -> ListEntitiesTextResponse:
        return ListEntitiesTextResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            disabled_by_default=bool(getattr(self, "disabled_by_default", False)),
            entity_category=self.entity_category,
            min_length=self.min_length,
            max_length=self.max_length,
            pattern=self.pattern,
            mode=self.mode,
        )

    async def build_state_response(self) -> TextStateResponse:
        return TextStateResponse(key=self.key, state=await self.get_state())

    async def get_state(self) -> str:
        return self._state

    async def set_state(self, value: str) -> None:
        value = str(value)
        if not self.min_length <= len(value) <= self.max_length:
            raise ValueError("text value is outside the configured length")
        changed = value != self._state
        self._state = value
        if changed:
            await self._publish_state()

    async def on_command(self, value: str) -> None:
        await self.set_state(value)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is TextCommandRequest and message.key == self.key:
            await self.on_command(message.state)


class CoverEntity(_StateEntity):
    DOMAIN = "cover"

    def __init__(
        self,
        *args: Any,
        position: float = 0.0,
        tilt: float = 0.0,
        current_operation: int = 0,
        legacy_state: int = 0,
        assumed_state: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.position, self.tilt = float(position), float(tilt)
        self.current_operation, self.legacy_state = current_operation, legacy_state
        self.assumed_state = bool(assumed_state)
        self.supports_position, self.supports_tilt, self.supports_stop = (
            True,
            False,
            True,
        )

    async def build_list_entities_response(self) -> ListEntitiesCoverResponse:
        return ListEntitiesCoverResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            assumed_state=self.assumed_state,
            supports_position=self.supports_position,
            supports_tilt=self.supports_tilt,
            device_class=self.device_class or "",
            icon=self.icon,
            entity_category=self.entity_category,
            supports_stop=self.supports_stop,
        )

    async def build_state_response(self) -> CoverStateResponse:
        return CoverStateResponse(
            key=self.key,
            legacy_state=self.legacy_state,
            position=self.position,
            tilt=self.tilt,
            current_operation=self.current_operation,
        )

    async def get_state(self) -> float:
        return self.position

    async def set_state(self, position: float) -> None:
        self.position = max(0.0, min(1.0, float(position)))
        await self._publish_state()

    async def on_command(self, command: CoverCommandRequest) -> None:
        if command.has_position:
            await self.set_state(command.position)
        if command.has_tilt:
            self.tilt = float(command.tilt)
        if command.stop:
            self.current_operation = 0
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is CoverCommandRequest and message.key == self.key:
            await self.on_command(message)


class FanEntity(_StateEntity):
    DOMAIN = "fan"

    def __init__(
        self,
        *args: Any,
        state: bool = False,
        oscillating: bool = False,
        speed: int = 0,
        direction: int = 0,
        speed_level: int = 0,
        preset_mode: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state, self.oscillating, self.speed, self.direction = (
            state,
            oscillating,
            speed,
            direction,
        )
        self.speed_level, self.preset_mode = speed_level, preset_mode
        self.supports_oscillation, self.supports_speed, self.supports_direction = (
            True,
            True,
            True,
        )
        self.supported_speed_count, self.supported_preset_modes = 3, []

    async def build_list_entities_response(self) -> ListEntitiesFanResponse:
        return ListEntitiesFanResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            supports_oscillation=self.supports_oscillation,
            supports_speed=self.supports_speed,
            supports_direction=self.supports_direction,
            supported_speed_count=self.supported_speed_count,
            icon=self.icon,
            entity_category=self.entity_category,
            supported_preset_modes=self.supported_preset_modes,
        )

    async def build_state_response(self) -> FanStateResponse:
        return FanStateResponse(
            key=self.key,
            state=self.state,
            oscillating=self.oscillating,
            speed=self.speed,
            direction=self.direction,
            speed_level=self.speed_level,
            preset_mode=self.preset_mode,
        )

    async def get_state(self) -> bool:
        return self.state

    async def set_state(self, value: bool) -> None:
        self.state = bool(value)
        await self._publish_state()

    async def on_command(self, command: FanCommandRequest) -> None:
        for attr in (
            "state",
            "oscillating",
            "speed",
            "direction",
            "speed_level",
            "preset_mode",
        ):
            if getattr(command, f"has_{attr}", False):
                setattr(self, attr, getattr(command, attr))
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is FanCommandRequest and message.key == self.key:
            await self.on_command(message)


class LockEntity(_StateEntity):
    DOMAIN = "lock"

    def __init__(self, *args: Any, state: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.assumed_state = False
        self.supports_open = False
        self.requires_code = False
        self.code_format = ""

    async def build_list_entities_response(self) -> ListEntitiesLockResponse:
        return ListEntitiesLockResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            assumed_state=self.assumed_state,
            supports_open=self.supports_open,
            requires_code=self.requires_code,
            code_format=self.code_format,
        )

    async def build_state_response(self) -> LockStateResponse:
        return LockStateResponse(key=self.key, state=self.state)

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: LockCommandRequest) -> None:
        state = {
            LockCommand.UNLOCK: LockState.UNLOCKED,
            LockCommand.LOCK: LockState.LOCKED,
            LockCommand.OPEN: LockState.OPEN,
        }.get(command.command)
        if state is not None:
            await self.set_state(state)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is LockCommandRequest and message.key == self.key:
            await self.on_command(message)


class MediaPlayerEntity(_StateEntity):
    DOMAIN = "media_player"

    def __init__(
        self,
        *args: Any,
        state: int = 1,
        volume: float = 1.0,
        muted: bool = False,
        feature_flags: int = 0,
        supported_formats: Sequence[Any] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state, self.volume, self.muted = state, float(volume), muted
        self.feature_flags, self.supported_formats = feature_flags, list(
            supported_formats
        )

    async def build_list_entities_response(self) -> ListEntitiesMediaPlayerResponse:
        return ListEntitiesMediaPlayerResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            supports_pause=True,
            supported_formats=self.supported_formats,
            feature_flags=self.feature_flags,
        )

    async def build_state_response(self) -> MediaPlayerStateResponse:
        return MediaPlayerStateResponse(
            key=self.key, state=self.state, volume=self.volume, muted=self.muted
        )

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: MediaPlayerCommandRequest) -> None:
        changed = False
        if command.has_volume:
            self.volume = command.volume
            changed = True
        if command.has_command:
            state = {
                MediaPlayerCommand.PLAY: MediaPlayerState.PLAYING,
                MediaPlayerCommand.PAUSE: MediaPlayerState.PAUSED,
                MediaPlayerCommand.STOP: MediaPlayerState.IDLE,
                MediaPlayerCommand.TURN_ON: MediaPlayerState.ON,
                MediaPlayerCommand.TURN_OFF: MediaPlayerState.OFF,
            }.get(command.command)
            if state is not None:
                self.state = state
                changed = True
            elif command.command == MediaPlayerCommand.MUTE:
                self.muted = True
                changed = True
            elif command.command == MediaPlayerCommand.UNMUTE:
                self.muted = False
                changed = True
        if changed:
            await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is MediaPlayerCommandRequest and message.key == self.key:
            await self.on_command(message)


class SirenEntity(_StateEntity):
    DOMAIN = "siren"

    def __init__(
        self,
        *args: Any,
        state: bool = False,
        tones: Sequence[str] = (),
        supports_duration: bool = False,
        supports_volume: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.tones = list(tones)
        self.supports_duration = supports_duration
        self.supports_volume = supports_volume

    async def build_list_entities_response(self) -> ListEntitiesSirenResponse:
        return ListEntitiesSirenResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            tones=self.tones,
            supports_duration=self.supports_duration,
            supports_volume=self.supports_volume,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> SirenStateResponse:
        return SirenStateResponse(key=self.key, state=self.state)

    async def get_state(self) -> bool:
        return self.state

    async def set_state(self, value: bool) -> None:
        self.state = bool(value)
        await self._publish_state()

    async def on_command(self, command: SirenCommandRequest) -> None:
        if command.has_state:
            await self.set_state(command.state)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is SirenCommandRequest and message.key == self.key:
            await self.on_command(message)


class ValveEntity(_StateEntity):
    DOMAIN = "valve"

    def __init__(
        self,
        *args: Any,
        position: float = 0.0,
        current_operation: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.position = position
        self.current_operation = current_operation
        self.supports_position = True
        self.supports_stop = True
        self.assumed_state = False

    async def build_list_entities_response(self) -> ListEntitiesValveResponse:
        return ListEntitiesValveResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class or "",
            assumed_state=self.assumed_state,
            supports_position=self.supports_position,
            supports_stop=self.supports_stop,
        )

    async def build_state_response(self) -> ValveStateResponse:
        return ValveStateResponse(
            key=self.key,
            position=self.position,
            current_operation=self.current_operation,
        )

    async def get_state(self) -> float:
        return self.position

    async def set_state(self, value: float) -> None:
        self.position = float(value)
        await self._publish_state()

    async def on_command(self, command: ValveCommandRequest) -> None:
        if command.has_position:
            await self.set_state(command.position)
        if command.stop:
            self.current_operation = 0
            await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is ValveCommandRequest and message.key == self.key:
            await self.on_command(message)


class WaterHeaterEntity(_StateEntity):
    DOMAIN = "water_heater"

    def __init__(
        self,
        *args: Any,
        current_temperature: float = 0.0,
        target_temperature: float = 0.0,
        target_temperature_low: float = 0.0,
        target_temperature_high: float = 0.0,
        mode: int = 0,
        state: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.current_temperature = current_temperature
        self.target_temperature = target_temperature
        self.target_temperature_low = target_temperature_low
        self.target_temperature_high = target_temperature_high
        self.mode = mode
        self.state = state
        self.min_temperature = 0.0
        self.max_temperature = 100.0
        self.target_temperature_step = 0.5
        self.supported_modes = []
        self.supported_features = 0
        self.temperature_unit = 0

    async def build_list_entities_response(self) -> ListEntitiesWaterHeaterResponse:
        return ListEntitiesWaterHeaterResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            min_temperature=self.min_temperature,
            max_temperature=self.max_temperature,
            target_temperature_step=self.target_temperature_step,
            supported_modes=self.supported_modes,
            supported_features=self.supported_features,
            temperature_unit=self.temperature_unit,
        )

    async def build_state_response(self) -> WaterHeaterStateResponse:
        return WaterHeaterStateResponse(
            key=self.key,
            current_temperature=self.current_temperature,
            target_temperature=self.target_temperature,
            mode=self.mode,
            state=self.state,
            target_temperature_low=self.target_temperature_low,
            target_temperature_high=self.target_temperature_high,
        )

    async def get_state(self) -> float:
        return self.target_temperature

    async def set_state(self, value: float) -> None:
        self.target_temperature = float(value)
        await self._publish_state()

    async def on_command(self, command: WaterHeaterCommandRequest) -> None:
        has_fields = command.has_fields
        changed = False
        if has_fields & WaterHeaterCommandField.MODE:
            self.mode = command.mode
            changed = True
        if has_fields & WaterHeaterCommandField.TARGET_TEMPERATURE:
            self.target_temperature = command.target_temperature
            changed = True
        if has_fields & WaterHeaterCommandField.TARGET_TEMPERATURE_LOW:
            self.target_temperature_low = command.target_temperature_low
            changed = True
        if has_fields & WaterHeaterCommandField.TARGET_TEMPERATURE_HIGH:
            self.target_temperature_high = command.target_temperature_high
            changed = True
        if has_fields & (
            WaterHeaterCommandField.AWAY_STATE | WaterHeaterCommandField.STATE
        ):
            away = bool(command.state & WaterHeaterStateFlag.AWAY)
            self.state = (
                self.state | int(WaterHeaterStateFlag.AWAY)
                if away
                else self.state & ~int(WaterHeaterStateFlag.AWAY)
            )
            changed = True
        if has_fields & (
            WaterHeaterCommandField.ON_STATE | WaterHeaterCommandField.STATE
        ):
            on = bool(command.state & WaterHeaterStateFlag.ON)
            self.state = (
                self.state | int(WaterHeaterStateFlag.ON)
                if on
                else self.state & ~int(WaterHeaterStateFlag.ON)
            )
            changed = True
        if changed:
            await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is WaterHeaterCommandRequest and message.key == self.key:
            await self.on_command(message)


class AlarmControlPanelEntity(_StateEntity):
    DOMAIN = "alarm_control_panel"

    def __init__(
        self,
        *args: Any,
        state: int = 0,
        supported_features: int = 0,
        requires_code: bool = False,
        requires_code_to_arm: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.supported_features = supported_features
        self.requires_code = requires_code
        self.requires_code_to_arm = requires_code_to_arm

    async def build_list_entities_response(
        self,
    ) -> ListEntitiesAlarmControlPanelResponse:
        return ListEntitiesAlarmControlPanelResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            supported_features=self.supported_features,
            requires_code=self.requires_code,
            requires_code_to_arm=self.requires_code_to_arm,
        )

    async def build_state_response(self) -> AlarmControlPanelStateResponse:
        return AlarmControlPanelStateResponse(key=self.key, state=self.state)

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: AlarmControlPanelCommandRequest) -> None:
        state = {
            AlarmControlPanelCommand.DISARM: AlarmControlPanelState.DISARMED,
            AlarmControlPanelCommand.ARM_AWAY: AlarmControlPanelState.ARMED_AWAY,
            AlarmControlPanelCommand.ARM_HOME: AlarmControlPanelState.ARMED_HOME,
            AlarmControlPanelCommand.ARM_NIGHT: AlarmControlPanelState.ARMED_NIGHT,
            AlarmControlPanelCommand.ARM_VACATION: AlarmControlPanelState.ARMED_VACATION,
            AlarmControlPanelCommand.ARM_CUSTOM_BYPASS: AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
            AlarmControlPanelCommand.TRIGGER: AlarmControlPanelState.TRIGGERED,
        }.get(command.command)
        if state is not None:
            await self.set_state(state)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is AlarmControlPanelCommandRequest and message.key == self.key:
            await self.on_command(message)


class DateEntity(_StateEntity):
    DOMAIN = "date"

    def __init__(
        self, *args: Any, year: int = 1970, month: int = 1, day: int = 1, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.year = year
        self.month = month
        self.day = day

    async def build_list_entities_response(self) -> ListEntitiesDateResponse:
        return ListEntitiesDateResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> DateStateResponse:
        return DateStateResponse(
            key=self.key, year=self.year, month=self.month, day=self.day
        )

    async def get_state(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    async def on_command(self, value: tuple[int, int, int]) -> None:
        self.year, self.month, self.day = value
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is DateCommandRequest and message.key == self.key:
            await self.on_command((message.year, message.month, message.day))


class DateTimeEntity(_StateEntity):
    DOMAIN = "datetime"

    def __init__(self, *args: Any, epoch_seconds: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.epoch_seconds = epoch_seconds

    async def build_list_entities_response(self) -> ListEntitiesDateTimeResponse:
        return ListEntitiesDateTimeResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> DateTimeStateResponse:
        return DateTimeStateResponse(key=self.key, epoch_seconds=self.epoch_seconds)

    async def get_state(self) -> int:
        return self.epoch_seconds

    async def set_state(self, value: int) -> None:
        self.epoch_seconds = int(value)
        await self._publish_state()

    async def on_command(self, value: int) -> None:
        await self.set_state(value)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is DateTimeCommandRequest and message.key == self.key:
            await self.on_command(message.epoch_seconds)


class TimeEntity(_StateEntity):
    DOMAIN = "time"

    def __init__(
        self, *args: Any, hour: int = 0, minute: int = 0, second: int = 0, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.hour = hour
        self.minute = minute
        self.second = second

    async def build_list_entities_response(self) -> ListEntitiesTimeResponse:
        return ListEntitiesTimeResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> TimeStateResponse:
        return TimeStateResponse(
            key=self.key, hour=self.hour, minute=self.minute, second=self.second
        )

    async def get_state(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"

    async def on_command(self, value: tuple[int, int, int]) -> None:
        self.hour, self.minute, self.second = value
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is TimeCommandRequest and message.key == self.key:
            await self.on_command((message.hour, message.minute, message.second))


class UpdateEntity(_StateEntity):
    DOMAIN = "update"

    def __init__(self, *args: Any, state: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.in_progress = False
        self.has_progress = False
        self.progress = 0.0
        self.current_version = ""
        self.latest_version = ""
        self.title = ""
        self.release_summary = ""
        self.release_url = ""

    async def build_list_entities_response(self) -> ListEntitiesUpdateResponse:
        return ListEntitiesUpdateResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class or "",
        )

    async def build_state_response(self) -> UpdateStateResponse:
        return UpdateStateResponse(
            key=self.key,
            state=self.state,
            in_progress=self.in_progress,
            has_progress=self.has_progress,
            progress=self.progress,
            current_version=self.current_version,
            latest_version=self.latest_version,
            title=self.title,
            release_summary=self.release_summary,
            release_url=self.release_url,
        )

    async def get_state(self) -> int:
        return self.state

    async def on_command(self, value: int) -> None:
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is UpdateCommandRequest and message.key == self.key:
            await self.on_command(message.command)


class EventEntity(BasicEntity):
    DOMAIN = "event"

    def __init__(
        self, *args: Any, event_types: Sequence[str] = (), **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.event_types = list(event_types)

    async def build_list_entities_response(self) -> ListEntitiesEventResponse:
        return ListEntitiesEventResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class or "",
            event_types=self.event_types,
        )

    async def trigger(self, event_type: str) -> None:
        await self.device.publish(
            self,
            "state_change",
            EventResponse(key=self.key, event_type=str(event_type)),
        )


class CameraEntity(BasicEntity):
    DOMAIN = "camera"

    async def build_list_entities_response(self) -> ListEntitiesCameraResponse:
        return ListEntitiesCameraResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
        )

    async def on_request(self, single: bool, stream: bool) -> None:
        """Override to capture a frame or start a stream."""

    async def on_command(self, single: bool, stream: bool) -> None:
        """Handle a camera request from Home Assistant."""
        await self.on_request(single, stream)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is CameraImageRequest:
            await self.on_command(message.single, message.stream)

    async def send_image(self, data: bytes, done: bool = True) -> None:
        for offset in range(0, max(len(data), 1), CAMERA_IMAGE_CHUNK_SIZE):
            chunk = data[offset : offset + CAMERA_IMAGE_CHUNK_SIZE]
            is_last = offset + len(chunk) >= len(data)
            await self.device.publish(
                self,
                "state_change",
                CameraImageResponse(
                    key=self.key, data=chunk, done=done if is_last else False
                ),
            )


class InfraredEntity(BasicEntity):
    DOMAIN = "infrared"

    def __init__(
        self,
        *args: Any,
        capabilities: int = 0,
        receiver_frequency: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.capabilities = capabilities
        self.receiver_frequency = receiver_frequency

    async def build_list_entities_response(self) -> ListEntitiesInfraredResponse:
        return ListEntitiesInfraredResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            capabilities=self.capabilities,
            receiver_frequency=self.receiver_frequency,
        )

    async def on_transmit(
        self,
        carrier_frequency: int,
        repeat_count: int,
        timings: Sequence[int],
        modulation: int,
    ) -> None:
        pass

    async def on_command(
        self,
        carrier_frequency: int,
        repeat_count: int,
        timings: Sequence[int],
        modulation: int,
    ) -> None:
        """Handle a raw transmit command from Home Assistant."""
        await self.on_transmit(carrier_frequency, repeat_count, timings, modulation)

    async def handle(self, key: str, message: Any) -> None:
        if (
            type(message) is InfraredRFTransmitRawTimingsRequest
            and message.key == self.key
        ):
            await self.on_command(
                message.carrier_frequency,
                message.repeat_count,
                tuple(message.timings),
                message.modulation,
            )

    async def publish_receive(self, timings: Sequence[int]) -> None:
        await self.device.publish(
            self, "state_change", InfraredRFReceiveEvent(key=self.key, timings=timings)
        )


class RadioFrequencyEntity(InfraredEntity):
    DOMAIN = "radio_frequency"

    def __init__(
        self,
        *args: Any,
        frequency_min: int = 0,
        frequency_max: int = 0,
        supported_modulations: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.frequency_min = frequency_min
        self.frequency_max = frequency_max
        self.supported_modulations = supported_modulations

    async def build_list_entities_response(self) -> ListEntitiesRadioFrequencyResponse:
        return ListEntitiesRadioFrequencyResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            capabilities=self.capabilities,
            frequency_min=self.frequency_min,
            frequency_max=self.frequency_max,
            supported_modulations=self.supported_modulations,
        )
