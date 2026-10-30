from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import CoverCommandRequest, CoverStateResponse, ListEntitiesCoverResponse
from aioesphomeapi.model import LegacyCoverCommand, LegacyCoverState
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["CoverEntity"]

class CoverEntity(_StateEntity):
    DOMAIN = "cover"

    def __init__(
        self,
        *args: Any,
        position: float = 0.0,
        tilt: float = 0.0,
        current_operation: int = 0,
        legacy_state: int | None = None,
        assumed_state: bool = False,
        supports_tilt: bool = False,
        supports_stop_tilt: bool = False,
        supports_toggle: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.position, self.tilt = float(position), float(tilt)
        self.current_operation = current_operation
        self.legacy_state = (
            legacy_state if legacy_state is not None
            else LegacyCoverState.CLOSED if self.position == 0 else LegacyCoverState.OPEN
        )
        self.assumed_state = bool(assumed_state)
        self.supports_stop_tilt = supports_stop_tilt
        self.supports_toggle = supports_toggle
        self.supports_position, self.supports_tilt, self.supports_stop = (
            True,
            supports_tilt,
            True,
        )

    async def build_list_entities_response(self) -> ListEntitiesCoverResponse:
        return ListEntitiesCoverResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            assumed_state=self.assumed_state,
            supports_position=self.supports_position,
            supports_tilt=self.supports_tilt,
            device_class=self.device_class or "",
            icon=self.icon,
            entity_category=self.entity_category,
            supports_stop=self.supports_stop,
            supports_stop_tilt=self.supports_stop_tilt,
            supports_toggle=self.supports_toggle,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )

    async def build_state_response(self) -> CoverStateResponse:
        return CoverStateResponse(
            key=self.key,
            legacy_state=self.legacy_state,
            position=self.position,
            tilt=self.tilt,
            current_operation=self.current_operation,
            device_id=self.device_id,
        )

    async def get_state(self) -> float:
        return self.position

    async def set_state(self, position: float) -> None:
        self.position = max(0.0, min(1.0, float(position)))
        self.legacy_state = (
            LegacyCoverState.CLOSED if self.position == 0 else LegacyCoverState.OPEN
        )
        await self._publish_state()

    async def on_command(self, command: CoverCommandRequest) -> None:
        if command.stop_tilt and self.supports_stop_tilt:
            await self.on_stop_tilt()
        if command.stop or (not command.has_position and
            command.has_legacy_command
            and command.legacy_command == LegacyCoverCommand.STOP
        ):
            self.current_operation = 0
            await self._publish_state()
            return
        if command.toggle and self.supports_toggle:
            await self.on_toggle()
        if command.has_position:
            await self.set_state(command.position)
        elif command.has_legacy_command and not command.stop:
            if command.legacy_command == LegacyCoverCommand.OPEN:
                await self.set_state(1.0)
            elif command.legacy_command == LegacyCoverCommand.CLOSE:
                await self.set_state(0.0)
        if (command.has_tilt and self.supports_tilt
            and not (command.stop_tilt and self.supports_stop_tilt)):
            self.tilt = max(0.0, min(1.0, float(command.tilt)))
        await self._publish_state()

    async def on_toggle(self) -> None:
        """Simulate stop while moving, otherwise close/open. Override for hardware."""
        if self.current_operation:
            self.current_operation = 0
        else:
            await self.set_state(1.0 if self.position == 0 else 0.0)

    async def on_stop_tilt(self) -> None:
        """Override to stop the tilt motor; the tilt position stays unchanged."""

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is CoverCommandRequest and message.key == self.key:
            await self.on_command(message)
