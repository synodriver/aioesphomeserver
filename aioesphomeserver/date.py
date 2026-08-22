from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import DateCommandRequest, DateStateResponse, ListEntitiesDateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["DateEntity"]

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
