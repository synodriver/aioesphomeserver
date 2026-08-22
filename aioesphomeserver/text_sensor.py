from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesTextSensorResponse, TextSensorStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["TextSensorEntity"]

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
