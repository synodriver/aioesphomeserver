from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from aioesphomeapi.api_pb2 import EventResponse, ListEntitiesEventResponse
from aioesphomeserver.basic_entity import BasicEntity

__all__ = ["EventEntity"]

class EventEntity(BasicEntity):
    DOMAIN = "event"

    def __init__(
        self, *args: Any, event_types: Sequence[str] = (), **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.event_types = list(event_types)

    async def build_list_entities_response(self) -> ListEntitiesEventResponse:
        return ListEntitiesEventResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class or "",
            event_types=self.event_types,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )

    async def trigger(self, event_type: str) -> None:
        device = self.device
        if device is None:
            raise RuntimeError("entity is not attached to a device")
        await device.publish(
            self,
            "state_change",
            EventResponse(key=self.key, event_type=str(event_type), device_id=self.device_id),
        )
