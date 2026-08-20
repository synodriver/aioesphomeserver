from __future__ import annotations

import json
from typing import Any

from aioesphomeapi.api_pb2 import (
    ListEntitiesNumberResponse,  # type: ignore
    NumberCommandRequest,
    NumberStateResponse,
)

from .basic_entity import BasicEntity


class NumberEntity(BasicEntity):
    DOMAIN = "number"

    def __init__(
        self,
        *args: Any,
        min_value: float | None = None,
        max_value: float | None = None,
        step: float | None = None,
        unit_of_measurement: str | None = None,
        mode: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.unit_of_measurement = unit_of_measurement
        self.mode = mode
        self._state = 0.0

    async def build_list_entities_response(self) -> ListEntitiesNumberResponse:
        return ListEntitiesNumberResponse(
            object_id=self.object_id,
            name=self.name,
            key=self.key,
            icon=self.icon,
            min_value=self.min_value,
            max_value=self.max_value,
            step=self.step,
            unit_of_measurement=self.unit_of_measurement,
            mode=self.mode,
            disabled_by_default=self.disabled_by_default,
            entity_category=self.entity_category,
        )

    async def build_state_response(self) -> NumberStateResponse:
        return NumberStateResponse(key=self.key, state=await self.get_state())

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

    async def on_command(self, value: float) -> None:
        """Handle a value requested by Home Assistant."""
        await self.set_state(value)

    async def handle(self, key: str, message: object) -> None:
        if type(message) is NumberCommandRequest and message.key == self.key:
            await self.on_command(message.state)


# Example usage
if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO)

    class TestDevice:
        async def log(self, level: int, domain: str, message: str) -> None:
            logging.log(level, message)

        async def notify_state_change(self) -> None:
            logging.info("State changed")

    async def main() -> None:
        device = TestDevice()
        number_entity = NumberEntity(
            device=device,
            name="Test Number",
            object_id="test_number",
            key=1,
            unique_id="unique_test_number",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            unit_of_measurement="%",
            mode=1,
        )

        await number_entity.set_state(50.0)
        print(await number_entity.build_list_entities_response())
        print(await number_entity.build_state_response())
        print(await number_entity.state_json())

    asyncio.run(main())
