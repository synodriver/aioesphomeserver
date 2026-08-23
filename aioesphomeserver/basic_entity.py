from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

from google.protobuf.message import Message

if TYPE_CHECKING:
    from aiohttp.web_urldispatcher import UrlDispatcher

    from aioesphomeserver.device import Device


class BasicEntity:
    DOMAIN = ""

    def __init__(
        self,
        name: str,
        object_id: str | None = None,
        unique_id: str | None = None,
        icon: str | None = None,
        device_class: str | None = None,
        entity_category: int | None = None,
        disabled_by_default: bool = False,
    ) -> None:
        self.name = name
        self._assigned_object_id = object_id
        self._assigned_unique_id = unique_id
        self.icon = icon
        self.device_class = device_class
        self.entity_category = entity_category
        self.disabled_by_default = disabled_by_default

        self.device: Device | None = None
        self.key: int | None = None

        # Concrete domains use bool, float, str, or protocol-specific state.
        self._state: Any = False

    def set_device(self, device: Device) -> None:
        self.device = device

    def set_key(self, key: int) -> None:
        self.key = key

    @property
    def object_id(self) -> str:
        if self._assigned_object_id is not None:
            return self._assigned_object_id
        else:
            obj_id = self.name.lower()
            obj_id = re.sub(r"\s+", "_", obj_id)
            obj_id = re.sub(r"[^\w]", "", obj_id)
            self._assigned_object_id = obj_id
            return obj_id

    @property
    def unique_id(self) -> str:
        if self._assigned_unique_id is not None:
            return self._assigned_unique_id
        else:
            m = hashlib.sha256()
            if self.device is None:
                raise RuntimeError("entity is not attached to a device")
            m.update(self.device.name.encode())
            m.update(self.device.mac_address.encode())
            m.update(self.object_id.encode())
            m.update(self.DOMAIN.encode())
            uid = m.hexdigest()[0:16]
            self._assigned_unique_id = uid
            return uid

    @property
    def json_id(self) -> str:
        return f"{self.DOMAIN}-{self.object_id}"

    async def build_list_entities_response(self) -> Message | None:
        return None

    async def build_state_response(self) -> Message | None:
        return None

    async def state_json(self) -> str | None:
        return None

    async def can_handle(self, key: str, message: Any) -> bool:
        return True

    async def handle(self, key: str, message: Any) -> None:
        return None

    async def add_routes(self, router: UrlDispatcher) -> None:
        return None

    async def notify_state_change(self) -> None:
        if self.device is None:
            raise RuntimeError("entity is not attached to a device")
        await self.device.publish(
            self, "state_change", await self.build_state_response()
        )
