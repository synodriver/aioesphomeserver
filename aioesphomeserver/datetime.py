from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import DateTimeCommandRequest, DateTimeStateResponse, ListEntitiesDateTimeResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["DateTimeEntity"]

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
