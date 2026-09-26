from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesSirenResponse, SirenCommandRequest, SirenStateResponse
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["SirenEntity"]

class SirenEntity(_StateEntity):
    DOMAIN = "siren"

    def __init__(
        self,
        *args: Any,
        state: bool = False,
        tones: Sequence[str] = (),
        supports_duration: bool = False,
        supports_volume: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.tones = list(tones)
        self.supports_duration = supports_duration
        self.supports_volume = supports_volume
        self.tone = ""
        self.duration = 0
        self.volume = 1.0

    async def build_list_entities_response(self) -> ListEntitiesSirenResponse:
        return ListEntitiesSirenResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            tones=self.tones,
            supports_duration=self.supports_duration,
            supports_volume=self.supports_volume,
            entity_category=self.entity_category,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )

    async def build_state_response(self) -> SirenStateResponse:
        return SirenStateResponse(key=self.key, state=self.state, device_id=self.device_id)

    async def get_state(self) -> bool:
        return self.state

    async def set_state(self, value: bool) -> None:
        self.state = bool(value)
        await self._publish_state()

    async def on_command(self, command: SirenCommandRequest) -> None:
        if command.has_state:
            await self.set_state(command.state)
        if command.has_tone:
            self.tone = command.tone
        if command.has_duration:
            self.duration = command.duration
        if command.has_volume:
            self.volume = command.volume

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is SirenCommandRequest and message.key == self.key:
            await self.on_command(message)
