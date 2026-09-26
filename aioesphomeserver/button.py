from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ButtonCommandRequest, ListEntitiesButtonResponse
from aioesphomeserver.basic_entity import BasicEntity

__all__ = ["ButtonEntity"]

class ButtonEntity(BasicEntity):
    DOMAIN = "button"

    async def build_list_entities_response(self) -> ListEntitiesButtonResponse:
        return ListEntitiesButtonResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            disabled_by_default=bool(getattr(self, "disabled_by_default", False)),
            entity_category=self.entity_category,
            device_class=self.device_class or "",
            device_id=self.device_id,
        )

    async def on_press(self) -> None:
        """Override to execute the application action."""

    async def on_command(self) -> None:
        """Handle a button command requested by Home Assistant."""
        await self.on_press()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is ButtonCommandRequest and message.key == self.key:
            await self.on_command()
