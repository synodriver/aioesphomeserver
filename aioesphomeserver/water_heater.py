from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import (
    ListEntitiesWaterHeaterResponse,
    WaterHeaterCommandRequest,
    WaterHeaterStateResponse,
)
from aioesphomeapi.model import WaterHeaterCommandField, WaterHeaterStateFlag
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["WaterHeaterEntity"]

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
        self.supported_modes: list[int] = []
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
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
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
            device_id=self.device_id,
            missing_state=self.missing_state,
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
