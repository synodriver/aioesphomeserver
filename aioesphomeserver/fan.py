from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import FanCommandRequest, FanStateResponse, ListEntitiesFanResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["FanEntity"]

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
        self.supported_speed_count = 3
        self.supported_preset_modes: list[str] = []

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
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
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
            device_id=self.device_id,
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
