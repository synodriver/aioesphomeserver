"""Backend-independent Z-Wave serial API bridge."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aioesphomeapi.api_pb2 import (
    ZWaveProxyFrame,
    ZWaveProxyRequest,
    ZWaveProxyRequestResponse,
)
from aioesphomeapi.model import ZWaveProxyFeature, ZWaveProxyRequestType, ZWaveProxyStatus

if TYPE_CHECKING:
    from aioesphomeserver.native_api_server import NativeApiConnection

logger = logging.getLogger(__name__)
__all__ = ["ZWaveProxy"]


class ZWaveProxy:
    """Override the hooks to connect a real Z-Wave controller."""

    def __init__(self, home_id: int = 0) -> None:
        self.home_id = home_id
        self.feature_flags = int(ZWaveProxyFeature.ENABLED)
        self.owner: NativeApiConnection | None = None

    async def on_subscribe(self) -> None:
        """Open the controller before acknowledging a subscription."""

    async def on_unsubscribe(self) -> None:
        """Close the controller when its subscriber leaves."""

    async def on_frame(self, data: bytes) -> None:
        """Write a frame received from the API client to the controller."""
        raise NotImplementedError("Z-Wave frame writing requires a backend")

    async def publish_frame(self, data: bytes) -> None:
        if self.owner is not None and self.owner.running:
            await self.owner.write_message(ZWaveProxyFrame(data=data))

    async def publish_home_id(self, home_id: int) -> None:
        """Notify the owner after the controller reports a Home ID change."""
        self.home_id = home_id
        if self.owner is not None and self.owner.running:
            await self.owner.write_message(
                ZWaveProxyRequest(
                    type=ZWaveProxyRequestType.HOME_ID_CHANGE,
                    data=home_id.to_bytes(4, "big"),
                )
            )

    async def handle_message(
        self, client: NativeApiConnection, message: ZWaveProxyFrame | ZWaveProxyRequest
    ) -> None:
        if isinstance(message, ZWaveProxyFrame):
            if self.owner is client:
                try:
                    await self.on_frame(message.data)
                except Exception:
                    logger.exception("Z-Wave frame write failed")
            return

        status = ZWaveProxyStatus.OK
        try:
            if message.type == ZWaveProxyRequestType.SUBSCRIBE:
                if self.owner is not None and self.owner is not client:
                    status = ZWaveProxyStatus.IN_USE
                elif self.owner is None:
                    await self.on_subscribe()
                    self.owner = client
            elif message.type == ZWaveProxyRequestType.UNSUBSCRIBE:
                if self.owner is client:
                    await self.on_unsubscribe()
                    self.owner = None
            else:
                status = ZWaveProxyStatus.NOT_SUPPORTED
        except Exception:
            logger.exception("Z-Wave subscription failed")
            status = ZWaveProxyStatus.NOT_SUPPORTED
        await client.write_message(
            ZWaveProxyRequestResponse(type=message.type, status=status)
        )

    async def on_api_client_disconnected(self, client: NativeApiConnection) -> None:
        if self.owner is client:
            self.owner = None
            try:
                await self.on_unsubscribe()
            except Exception:
                logger.exception("Z-Wave cleanup failed")
