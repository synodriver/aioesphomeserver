from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesUpdateResponse, UpdateCommandRequest, UpdateStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["UpdateEntity"]

class UpdateEntity(_StateEntity):
    DOMAIN = "update"

    def __init__(self, *args: Any, missing_state: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.missing_state = bool(missing_state)
        self.in_progress = False
        self.has_progress = False
        self.progress = 0.0
        self.current_version = ""
        self.latest_version = ""
        self.title = ""
        self.release_summary = ""
        self.release_url = ""

    async def build_list_entities_response(self) -> ListEntitiesUpdateResponse:
        return ListEntitiesUpdateResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class or "",
        )

    async def build_state_response(self) -> UpdateStateResponse:
        return UpdateStateResponse(
            key=self.key,
            missing_state=self.missing_state,
            in_progress=self.in_progress,
            has_progress=self.has_progress,
            progress=self.progress,
            current_version=self.current_version,
            latest_version=self.latest_version,
            title=self.title,
            release_summary=self.release_summary,
            release_url=self.release_url,
        )

    async def get_state(self) -> bool:
        return self.missing_state

    async def on_command(self, value: int) -> None:
        await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is UpdateCommandRequest and message.key == self.key:
            await self.on_command(message.command)
