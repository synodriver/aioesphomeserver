from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesValveResponse, ValveCommandRequest, ValveStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["ValveEntity"]

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
