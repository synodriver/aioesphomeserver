from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesLockResponse, LockCommandRequest, LockStateResponse
from aioesphomeapi.model import LockCommand, LockState
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["LockEntity"]

class LockEntity(_StateEntity):
    DOMAIN = "lock"

    def __init__(self, *args: Any, state: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.assumed_state = False
        self.supports_open = False
        self.requires_code = False
        self.code_format = ""

    async def build_list_entities_response(self) -> ListEntitiesLockResponse:
        return ListEntitiesLockResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            assumed_state=self.assumed_state,
            supports_open=self.supports_open,
            requires_code=self.requires_code,
            code_format=self.code_format,
        )

    async def build_state_response(self) -> LockStateResponse:
        return LockStateResponse(key=self.key, state=self.state)

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: LockCommandRequest) -> None:
        state = {
            LockCommand.UNLOCK: LockState.UNLOCKED,
            LockCommand.LOCK: LockState.LOCKED,
            LockCommand.OPEN: LockState.OPEN,
        }.get(command.command)
        if state is not None:
            await self.set_state(state)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is LockCommandRequest and message.key == self.key:
            await self.on_command(message)
