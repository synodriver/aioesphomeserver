from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import CoverCommandRequest, CoverStateResponse, ListEntitiesCoverResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["CoverEntity"]

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
