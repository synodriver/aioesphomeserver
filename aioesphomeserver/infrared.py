from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from aioesphomeapi.api_pb2 import InfraredRFReceiveEvent, InfraredRFTransmitRawTimingsRequest, ListEntitiesInfraredResponse
from aioesphomeserver.basic_entity import BasicEntity

__all__ = ["InfraredEntity"]

class InfraredEntity(BasicEntity):
    DOMAIN = "infrared"

    def __init__(
        self,
        *args: Any,
        capabilities: int = 0,
        receiver_frequency: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.capabilities = capabilities
        self.receiver_frequency = receiver_frequency

    async def build_list_entities_response(self) -> ListEntitiesInfraredResponse:
        return ListEntitiesInfraredResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            capabilities=self.capabilities,
            receiver_frequency=self.receiver_frequency,
        )

    async def on_transmit(
        self,
        carrier_frequency: int,
        repeat_count: int,
        timings: Sequence[int],
        modulation: int,
    ) -> None:
        pass

    async def on_command(
        self,
        carrier_frequency: int,
        repeat_count: int,
        timings: Sequence[int],
        modulation: int,
    ) -> None:
        """Handle a raw transmit command from Home Assistant."""
        await self.on_transmit(carrier_frequency, repeat_count, timings, modulation)

    async def handle(self, key: str, message: Any) -> None:
        if (
            type(message) is InfraredRFTransmitRawTimingsRequest
            and message.key == self.key
        ):
            await self.on_command(
                message.carrier_frequency,
                message.repeat_count,
                tuple(message.timings),
                message.modulation,
            )

    async def publish_receive(self, timings: Sequence[int]) -> None:
        await self.device.publish(
            self, "state_change", InfraredRFReceiveEvent(key=self.key, timings=timings)
        )
