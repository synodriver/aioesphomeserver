from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesTimeResponse, TimeCommandRequest, TimeStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["TimeEntity"]

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
