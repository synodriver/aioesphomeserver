from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import AlarmControlPanelCommandRequest, AlarmControlPanelStateResponse, ListEntitiesAlarmControlPanelResponse
from aioesphomeapi.model import AlarmControlPanelCommand, AlarmControlPanelState
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["AlarmControlPanelEntity"]

class AlarmControlPanelEntity(_StateEntity):
    DOMAIN = "alarm_control_panel"

    def __init__(
        self,
        *args: Any,
        state: int = 0,
        supported_features: int = 0,
        requires_code: bool = False,
        requires_code_to_arm: bool = False,
        code: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state = state
        self.supported_features = supported_features
        self.requires_code = requires_code
        self.requires_code_to_arm = requires_code_to_arm
        self.code = code

    async def build_list_entities_response(
        self,
    ) -> ListEntitiesAlarmControlPanelResponse:
        return ListEntitiesAlarmControlPanelResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            supported_features=self.supported_features,
            requires_code=self.requires_code,
            requires_code_to_arm=self.requires_code_to_arm,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )

    async def build_state_response(self) -> AlarmControlPanelStateResponse:
        return AlarmControlPanelStateResponse(
            key=self.key, state=self.state, device_id=self.device_id
        )

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: AlarmControlPanelCommandRequest) -> None:
        is_arm_command = command.command in (
            AlarmControlPanelCommand.ARM_AWAY,
            AlarmControlPanelCommand.ARM_HOME,
            AlarmControlPanelCommand.ARM_NIGHT,
            AlarmControlPanelCommand.ARM_VACATION,
            AlarmControlPanelCommand.ARM_CUSTOM_BYPASS,
        )
        if (
            (command.command == AlarmControlPanelCommand.DISARM and self.requires_code)
            or (is_arm_command and self.requires_code_to_arm)
        ) and (self.code is None or command.code != self.code):
            return
        state = {
            AlarmControlPanelCommand.DISARM: AlarmControlPanelState.DISARMED,
            AlarmControlPanelCommand.ARM_AWAY: AlarmControlPanelState.ARMED_AWAY,
            AlarmControlPanelCommand.ARM_HOME: AlarmControlPanelState.ARMED_HOME,
            AlarmControlPanelCommand.ARM_NIGHT: AlarmControlPanelState.ARMED_NIGHT,
            AlarmControlPanelCommand.ARM_VACATION: AlarmControlPanelState.ARMED_VACATION,
            AlarmControlPanelCommand.ARM_CUSTOM_BYPASS: AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
            AlarmControlPanelCommand.TRIGGER: AlarmControlPanelState.TRIGGERED,
        }.get(command.command)
        if state is not None:
            await self.set_state(state)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is AlarmControlPanelCommandRequest and message.key == self.key:
            await self.on_command(message)
