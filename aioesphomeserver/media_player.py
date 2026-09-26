from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from aioesphomeapi.api_pb2 import ListEntitiesMediaPlayerResponse, MediaPlayerCommandRequest, MediaPlayerStateResponse
from aioesphomeapi.model import MediaPlayerCommand, MediaPlayerState
from aioesphomeserver.state_entity import _StateEntity

__all__ = ["MediaPlayerEntity"]

class MediaPlayerEntity(_StateEntity):
    DOMAIN = "media_player"

    def __init__(
        self,
        *args: Any,
        state: int = 1,
        volume: float = 1.0,
        muted: bool = False,
        feature_flags: int = 0,
        supported_formats: Sequence[Any] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.state, self.volume, self.muted = state, float(volume), muted
        self.feature_flags, self.supported_formats = feature_flags, list(
            supported_formats
        )

    async def build_list_entities_response(self) -> ListEntitiesMediaPlayerResponse:
        return ListEntitiesMediaPlayerResponse(
            object_id=self.object_id,
            key=self.key,
            name=self.name,
            icon=self.icon,
            entity_category=self.entity_category,
            supports_pause=True,
            supported_formats=self.supported_formats,
            feature_flags=self.feature_flags,
            disabled_by_default=self.disabled_by_default,
            device_id=self.device_id,
        )

    async def build_state_response(self) -> MediaPlayerStateResponse:
        return MediaPlayerStateResponse(
            key=self.key, state=self.state, volume=self.volume, muted=self.muted,
            device_id=self.device_id,
        )

    async def get_state(self) -> int:
        return self.state

    async def set_state(self, value: int) -> None:
        self.state = value
        await self._publish_state()

    async def on_command(self, command: MediaPlayerCommandRequest) -> None:
        changed = False
        if command.has_volume:
            self.volume = command.volume
            changed = True
        if command.has_command:
            state = {
                MediaPlayerCommand.PLAY: MediaPlayerState.PLAYING,
                MediaPlayerCommand.PAUSE: MediaPlayerState.PAUSED,
                MediaPlayerCommand.STOP: MediaPlayerState.IDLE,
                MediaPlayerCommand.TURN_ON: MediaPlayerState.ON,
                MediaPlayerCommand.TURN_OFF: MediaPlayerState.OFF,
            }.get(command.command)
            if state is not None:
                self.state = state
                changed = True
            elif command.command == MediaPlayerCommand.MUTE:
                self.muted = True
                changed = True
            elif command.command == MediaPlayerCommand.UNMUTE:
                self.muted = False
                changed = True
            elif command.command == MediaPlayerCommand.TOGGLE:
                self.state = (
                    MediaPlayerState.OFF
                    if self.state != MediaPlayerState.OFF
                    else MediaPlayerState.ON
                )
                changed = True
            elif command.command == MediaPlayerCommand.VOLUME_UP:
                self.volume = min(1.0, self.volume + 0.1)
                changed = True
            elif command.command == MediaPlayerCommand.VOLUME_DOWN:
                self.volume = max(0.0, self.volume - 0.1)
                changed = True
        # URL and announcement are transport hints for the application
        # backend.  Keep them available to subclasses without prescribing a
        # media implementation.
        if command.has_media_url:
            self.media_url = command.media_url
            changed = True
        if command.has_announcement:
            self.announcement = command.announcement
            changed = True
        if changed:
            await self._publish_state()

    async def handle(self, key: str, message: Any) -> None:
        if type(message) is MediaPlayerCommandRequest and message.key == self.key:
            await self.on_command(message)
