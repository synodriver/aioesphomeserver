from __future__ import annotations

import json
from typing import Any

from aioesphomeapi.api_pb2 import (
    BinarySensorStateResponse,  # type: ignore
    ListEntitiesBinarySensorResponse,
)

from aioesphomeserver.basic_entity import BasicEntity


class BinarySensorEntity(BasicEntity):
    DOMAIN = "binary_sensor"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._state = False

    async def build_list_entities_response(self) -> ListEntitiesBinarySensorResponse:
        return ListEntitiesBinarySensorResponse(
            object_id=self.object_id,
            name=self.name,
            key=self.key,
            device_class=self.device_class,
            icon=self.icon,
            disabled_by_default=self.disabled_by_default,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> BinarySensorStateResponse:
        return BinarySensorStateResponse(key=self.key, state=await self.get_state())

    async def state_json(self) -> str:
        state = await self.get_state()
        state_str = "ON" if state else "OFF"

        data = {
            "id": self.json_id,
            "name": self.name,
            "state": state_str,
            "value": state,
        }
        return json.dumps(data)

    async def get_state(self) -> bool:
        return self._state

    async def set_state(self, val: bool) -> None:
        if self.device is None:
            raise RuntimeError("entity is not attached to a device")
        old_state = self._state
        self._state = val
        if val != old_state:
            await self.notify_state_change()
