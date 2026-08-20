from __future__ import annotations

import json
from typing import Any

from . import BasicEntity, ListEntitiesSensorResponse, SensorStateResponse


class SensorEntity(BasicEntity):
    DOMAIN = "sensor"

    def __init__(
        self,
        *args: Any,
        unit_of_measurement: str | None = None,
        accuracy_decimals: int | None = None,
        state_class: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.unit_of_measurement = unit_of_measurement
        self.accuracy_decimals = accuracy_decimals
        self.state_class = state_class
        self._state = 0.0

    async def build_list_entities_response(self) -> ListEntitiesSensorResponse:
        return ListEntitiesSensorResponse(
            object_id=self.object_id,
            name=self.name,
            key=self.key,
            icon=self.icon,
            unit_of_measurement=self.unit_of_measurement,
            accuracy_decimals=self.accuracy_decimals,
            device_class=self.device_class,
            state_class=self.state_class,
            disabled_by_default=self.disabled_by_default,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> SensorStateResponse:
        return SensorStateResponse(key=self.key, state=await self.get_state())

    async def state_json(self) -> str:
        state = await self.get_state()

        data = {
            "id": self.json_id,
            "name": self.name,
            "state": state,
        }
        return json.dumps(data)

    async def get_state(self) -> float:
        return self._state

    async def set_state(self, val: float) -> None:
        if self.device is None:
            raise RuntimeError("entity is not attached to a device")
        await self.device.log(
            3, self.DOMAIN, f"[{self.object_id}] Setting value to {val}"
        )
        old_state = self._state
        self._state = val
        if val != old_state:
            await self.notify_state_change()
