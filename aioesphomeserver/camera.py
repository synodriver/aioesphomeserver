from __future__ import annotations

from typing import Any
from aioesphomeapi.api_pb2 import (
    CameraImageRequest,
    CameraImageResponse,
    ListEntitiesCameraResponse,
)
from aioesphomeserver.basic_entity import BasicEntity

CAMERA_IMAGE_CHUNK_SIZE = 1390

__all__ = ["CAMERA_IMAGE_CHUNK_SIZE", "CameraEntity"]

class CameraEntity(BasicEntity):
    DOMAIN = "camera"

    async def build_list_entities_response(self) -> ListEntitiesCameraResponse:
        return ListEntitiesCameraResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
        )

    async def on_request(self, single: bool, stream: bool) -> None:
        """Override to capture a frame or start a stream."""

    async def on_command(self, single: bool, stream: bool) -> None:
        """Handle a camera request from Home Assistant."""
        await self.on_request(single, stream)

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is CameraImageRequest:
            await self.on_command(message.single, message.stream)

    async def send_image(self, data: bytes, done: bool = True) -> None:
        for offset in range(0, max(len(data), 1), CAMERA_IMAGE_CHUNK_SIZE):
            chunk = data[offset : offset + CAMERA_IMAGE_CHUNK_SIZE]
            is_last = offset + len(chunk) >= len(data)
            device = self.device
            if device is None:
                raise RuntimeError("entity is not attached to a device")
            await device.publish(
                self,
                "state_change",
                CameraImageResponse(
                    key=self.key, data=chunk, done=done if is_last else False
                ),
            )
