"""ESPHome onboarding wizard descriptions and runtime input selections."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence

from aioesphomeapi.api_pb2 import DeviceWizardResponse, WizardInputSetRequest
from aioesphomeapi.model import (
    WizardEntityField,
    WizardEntityFilter,
    WizardInputField,
    WizardPage,
)

from aioesphomeserver._compression import compress
from aioesphomeserver.services import _fnv1_hash


class OnboardingWizard:
    """Describe a version 1 wizard; override on_input to apply HA selections.

    Selections live in RAM. Clients must resend their saved choices after each
    connection, before subscribing to Home Assistant states.
    """

    def __init__(self, pages: Sequence[WizardPage]) -> None:
        self._inputs: dict[int, WizardInputField] = {}
        for page in pages:
            if any(not 0 <= item.key <= 0xFFFFFFFF for item in page.entities) or any(
                not 0 <= entry.key <= 0xFFFFFFFF for entry in page.inputs
            ):
                raise ValueError("wizard keys must fit uint32")
            for entry in page.inputs:
                if entry.key in self._inputs:
                    raise ValueError("wizard input keys must be unique")
                if not 1 <= entry.max_length <= 4095:
                    raise ValueError("wizard input max_length must be 1..4095")
                self._inputs[entry.key] = entry
        document = json.dumps(
            {"version": 1, "pages": [page.to_dict() for page in pages]},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(document) > 1024 * 1024:
            raise ValueError("wizard JSON exceeds the client's 1 MiB limit")
        self._data = compress(document)
        # Noise needs four bytes of message metadata and a 16-byte auth tag.
        if DeviceWizardResponse(data=self._data).ByteSize() > 65535 - 20:
            raise ValueError("compressed wizard exceeds the Native API Noise frame limit")
        self._selections: dict[int, tuple[str, ...]] = {}
        self._input_locks = {key: asyncio.Lock() for key in self._inputs}

    @staticmethod
    def input_key(input_id: str) -> int:
        """Hash an ESPHome input id (independent of the entity discovery key)."""
        return _fnv1_hash(input_id)

    @property
    def selections(self) -> Mapping[int, tuple[str, ...]]:
        return dict(self._selections)

    def response(self) -> DeviceWizardResponse:
        return DeviceWizardResponse(data=self._data)

    async def handle_input(self, request: WizardInputSetRequest) -> None:
        entry = self._inputs.get(request.key)
        if entry is None or len(request.entity_id.encode("utf-8")) > 4095:
            return
        entity_ids = (
            tuple(value.strip() for value in request.entity_id.split(","))
            if entry.multiple else (request.entity_id,)
        )
        if (not entry.multiple and len(entity_ids) != 1) or any(
            not value or "." not in value or "," in value
            or len(value.encode("utf-8")) > 255
            for value in entity_ids
        ):
            return
        if entry.multiple and len(",".join(entity_ids).encode("utf-8")) > entry.max_length:
            return
        async with self._input_locks[request.key]:
            if self._selections.get(request.key) == entity_ids:
                return
            await self.on_input(request.key, entity_ids)
            self._selections[request.key] = entity_ids

    async def on_input(self, key: int, entity_ids: tuple[str, ...]) -> None:
        """Apply a changed selection to the application's HA input backend."""


__all__ = [
    "OnboardingWizard", "WizardEntityField", "WizardEntityFilter",
    "WizardInputField", "WizardPage",
]
