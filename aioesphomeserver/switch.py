from __future__ import annotations

import json
from typing import Any

from aioesphomeapi.api_pb2 import (
    ListEntitiesSwitchResponse,  # type: ignore
    SwitchCommandRequest,
    SwitchStateResponse,
)
from aiohttp import web

from aioesphomeserver.basic_entity import BasicEntity


class SwitchEntity(BasicEntity):
    DOMAIN = "switch"

    def __init__(
        self, *args: Any, assumed_state: bool | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)

        self.assumed_state = assumed_state
        self._state = False

    async def build_list_entities_response(self) -> ListEntitiesSwitchResponse:
        return ListEntitiesSwitchResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            device_class=self.device_class,
            assumed_state=self.assumed_state,
            disabled_by_default=self.disabled_by_default,
        )

    async def build_state_response(self) -> SwitchStateResponse:
        return SwitchStateResponse(key=self.key, state=await self.get_state())

    async def get_state(self) -> bool:
        return self._state

    async def set_state(self, val: bool) -> None:
        if self.device is None:
            raise RuntimeError("entity is not attached to a device")
        await self.device.log(
            3, self.DOMAIN, f"[{self.object_id}] Setting state to {val}"
        )
        old_state = self._state
        self._state = val
        if val != old_state:
            await self.notify_state_change()

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

    async def add_routes(self, router: Any) -> None:
        router.add_route("GET", f"/switch/{self.object_id}", self.route_get_state)
        router.add_route(
            "POST", f"/switch/{self.object_id}/turn_on", self.route_turn_on
        )
        router.add_route(
            "POST", f"/switch/{self.object_id}/turn_off", self.route_turn_off
        )

    async def route_get_state(self, request: Any) -> web.Response:
        data = await self.state_json()
        return web.Response(text=data)

    async def route_turn_off(self, request: Any) -> web.Response:
        await self.set_state(False)
        data = await self.state_json()
        return web.Response(text=data)

    async def route_turn_on(self, request: Any) -> web.Response:
        await self.set_state(True)
        data = await self.state_json()
        return web.Response(text=data)

    async def on_command(self, value: bool) -> None:
        """Handle a state requested by Home Assistant."""
        await self.set_state(value)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) == SwitchCommandRequest:
            if message.key == self.key:
                await self.on_command(message.state)
