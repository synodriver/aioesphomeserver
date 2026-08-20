from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from aioesphomeapi.api_pb2 import (  # type: ignore
    ListEntitiesSelectResponse,
    SelectCommandRequest,
    SelectStateResponse,
)

from .basic_entity import BasicEntity


class SelectEntity(BasicEntity):
    DOMAIN = "select"

    def __init__(
        self,
        *args: Any,
        options: Sequence[str],
        initial_state: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.options = tuple(options)
        if not self.options:
            raise ValueError("SelectEntity requires at least one option")

        self._state = initial_state if initial_state is not None else self.options[0]
        if self._state not in self.options:
            raise ValueError("initial_state must be one of the select options")

    async def build_list_entities_response(self) -> ListEntitiesSelectResponse:
        return ListEntitiesSelectResponse(
            object_id=self.object_id,
            name=self.name,
            key=self.key,
            icon=self.icon,
            options=self.options,
            disabled_by_default=self.disabled_by_default,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> SelectStateResponse:
        return SelectStateResponse(key=self.key, state=await self.get_state())

    async def state_json(self) -> str:
        return json.dumps(
            {
                "id": self.json_id,
                "name": self.name,
                "state": await self.get_state(),
                "options": self.options,
            }
        )

    async def get_state(self) -> str:
        return self._state

    async def set_state(self, value: str) -> None:
        if self.device is None:
            raise RuntimeError("entity is not attached to a device")
        if value not in self.options:
            raise ValueError(f"unsupported select option: {value}")

        await self.device.log(
            3, self.DOMAIN, f"[{self.object_id}] Setting value to {value}"
        )
        old_state = self._state
        self._state = value
        if value != old_state:
            await self.notify_state_change()

    async def on_command(self, value: str) -> None:
        """Handle an option requested by Home Assistant."""
        await self.set_state(value)

    async def handle(self, key: str, message: object) -> None:
        if type(message) is SelectCommandRequest and message.key == self.key:
            await self.on_command(message.state)
