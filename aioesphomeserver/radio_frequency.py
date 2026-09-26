from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesRadioFrequencyResponse
from aioesphomeserver.infrared import InfraredEntity

__all__ = ["RadioFrequencyEntity"]

class RadioFrequencyEntity(InfraredEntity):
    DOMAIN = "radio_frequency"

    def __init__(
        self,
        *args: Any,
        frequency_min: int = 0,
        frequency_max: int = 0,
        supported_modulations: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.frequency_min = frequency_min
        self.frequency_max = frequency_max
        self.supported_modulations = supported_modulations

    async def build_list_entities_response(self) -> ListEntitiesRadioFrequencyResponse:
        return ListEntitiesRadioFrequencyResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            capabilities=self.capabilities,
            frequency_min=self.frequency_min,
            frequency_max=self.frequency_max,
            supported_modulations=self.supported_modulations,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )
