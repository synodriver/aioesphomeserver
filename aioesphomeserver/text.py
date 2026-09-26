from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesTextResponse, TextCommandRequest, TextStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["TextEntity"]

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
            device_id=self.device_id,
        )

    async def build_state_response(self) -> TextStateResponse:
        return TextStateResponse(
            key=self.key, state=await self.get_state(),
            missing_state=self.missing_state, device_id=self.device_id,
        )

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
