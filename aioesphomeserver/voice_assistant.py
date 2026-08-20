from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aioesphomeapi.api_pb2 import (
    SubscribeVoiceAssistantRequest,
    VoiceAssistantAnnounceFinished,
    VoiceAssistantAnnounceRequest,
    VoiceAssistantAudio,
    VoiceAssistantAudioSettings,
    VoiceAssistantConfigurationRequest,
    VoiceAssistantConfigurationResponse,
    VoiceAssistantEventResponse,
    VoiceAssistantRequest,
    VoiceAssistantResponse,
    VoiceAssistantSetConfiguration,
    VoiceAssistantTimerEventResponse,
)
from aioesphomeapi.api_pb2 import (
    VoiceAssistantWakeWord as VoiceAssistantWakeWordProto,
)  # type: ignore
from aioesphomeapi.model import (
    VoiceAssistantCommandFlag,
    VoiceAssistantEventType,
    VoiceAssistantFeature,
    VoiceAssistantTimerEventType,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from google.protobuf.message import Message

    from .native_api_server import NativeApiConnection


logger = logging.getLogger(__name__)


__all__ = [
    "VoiceAssistant",
    "VoiceAssistantAudioConfig",
    "VoiceAssistantConfiguration",
    "VoiceAssistantError",
    "VoiceAssistantEventType",
    "VoiceAssistantExternalWakeWordConfig",
    "VoiceAssistantFeature",
    "VoiceAssistantNotSubscribedError",
    "VoiceAssistantStartError",
    "VoiceAssistantTimer",
    "VoiceAssistantTimerEventType",
    "VoiceAssistantWakeWordConfig",
]


@dataclass(frozen=True, slots=True)
class VoiceAssistantAudioConfig:
    """Audio processing settings sent to Home Assistant."""

    noise_suppression_level: int = 0
    auto_gain: int = 0
    volume_multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class VoiceAssistantWakeWordConfig:
    id: str
    wake_word: str
    trained_languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceAssistantExternalWakeWordConfig:
    id: str
    wake_word: str
    trained_languages: tuple[str, ...] = ()
    model_type: str = ""
    model_size: int = 0
    model_hash: str = ""
    url: str = ""


@dataclass(frozen=True, slots=True)
class VoiceAssistantConfiguration:
    available_wake_words: tuple[VoiceAssistantWakeWordConfig, ...] = ()
    active_wake_words: tuple[str, ...] = ()
    max_active_wake_words: int = 0


@dataclass(frozen=True, slots=True)
class VoiceAssistantTimer:
    event_type: VoiceAssistantTimerEventType
    timer_id: str
    name: str
    total_seconds: int
    seconds_left: int
    is_active: bool


class VoiceAssistantError(Exception):
    """Base exception for voice assistant protocol errors."""


class VoiceAssistantNotSubscribedError(VoiceAssistantError):
    """Home Assistant has not subscribed to the voice assistant endpoint."""


class VoiceAssistantStartError(VoiceAssistantError):
    """Home Assistant could not start an Assist pipeline."""


class VoiceAssistant:
    """ESPHome-compatible, backend-neutral voice assistant endpoint.

    The application owns microphone capture and speaker/media playback. Use
    ``start`` and ``send_audio`` for microphone input, and override the
    ``on_*`` methods for messages sent by Home Assistant.
    """

    def __init__(
        self,
        *,
        output_only: bool = False,
        speaker: bool = False,
        timers: bool = False,
        announcements: bool = False,
        start_conversation: bool = False,
        multi_channel_audio: bool = False,
        available_wake_words: "Sequence[VoiceAssistantWakeWordConfig]" = (),
        active_wake_words: "Sequence[str]" = (),
        max_active_wake_words: int = 0,
    ) -> None:
        if max_active_wake_words < 0:
            raise ValueError("max_active_wake_words must be non-negative")
        if output_only and multi_channel_audio:
            raise ValueError(
                "output-only voice assistants cannot use microphone channels"
            )

        features = VoiceAssistantFeature.API_AUDIO
        if not output_only:
            features |= VoiceAssistantFeature.VOICE_ASSISTANT
        if speaker:
            features |= VoiceAssistantFeature.SPEAKER
        if timers:
            features |= VoiceAssistantFeature.TIMERS
        if announcements or output_only or start_conversation:
            features |= VoiceAssistantFeature.ANNOUNCE
        if start_conversation:
            features |= VoiceAssistantFeature.START_CONVERSATION
        if multi_channel_audio:
            features |= VoiceAssistantFeature.MULTI_CHANNEL_AUDIO

        self.feature_flags = int(features)
        self.legacy_version = 2 if speaker else 1
        self.device = None
        self._output_only = output_only
        self._multi_channel_audio = multi_channel_audio
        self._client: NativeApiConnection | None = None
        self._subscription_flags = 0
        self._subscribed_event = asyncio.Event()
        self._start_future: asyncio.Future[int] | None = None
        self._stream_port: int | None = None
        self._pipeline_active = False
        self._announcement_tasks: set[asyncio.Task[None]] = set()
        self._configuration = VoiceAssistantConfiguration(
            available_wake_words=tuple(available_wake_words),
            active_wake_words=tuple(active_wake_words),
            max_active_wake_words=max_active_wake_words,
        )

    @property
    def is_subscribed(self) -> bool:
        return self._client is not None

    @property
    def stream_port(self) -> int | None:
        """Zero means API audio; a positive value means HA requested UDP."""
        return self._stream_port

    @property
    def is_pipeline_active(self) -> bool:
        return self._pipeline_active

    @property
    def is_streaming_audio(self) -> bool:
        return self._stream_port is not None

    async def wait_until_subscribed(self, timeout: float | None = None) -> None:
        """Wait until a Home Assistant client subscribes."""
        if timeout is None:
            await self._subscribed_event.wait()
        else:
            await asyncio.wait_for(self._subscribed_event.wait(), timeout)

    async def start(
        self,
        *,
        conversation_id: str = "",
        use_vad: bool = True,
        use_wake_word: bool = False,
        audio: VoiceAssistantAudioConfig | None = None,
        wake_word_phrase: str = "",
        timeout: float = 10.0,
    ) -> int:
        """Request an Assist pipeline and return its audio port.

        A return value of ``0`` selects protobuf API audio. A positive value
        selects legacy UDP audio; the application is responsible for sending
        microphone data to that port.
        """
        client = self._require_client()
        if self._output_only:
            raise VoiceAssistantError("an output-only endpoint cannot start Assist")
        if self._pipeline_active:
            raise VoiceAssistantError("an Assist pipeline is already active")
        if self._start_future is not None and not self._start_future.done():
            raise VoiceAssistantError(
                "a voice assistant start request is already pending"
            )

        flags = VoiceAssistantCommandFlag(0)
        if use_vad:
            flags |= VoiceAssistantCommandFlag.USE_VAD
        if use_wake_word:
            flags |= VoiceAssistantCommandFlag.USE_WAKE_WORD
        audio = audio or VoiceAssistantAudioConfig()

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._start_future = future
        try:
            await client.write_message(
                VoiceAssistantRequest(
                    start=True,
                    conversation_id=conversation_id,
                    flags=int(flags),
                    audio_settings=VoiceAssistantAudioSettings(
                        noise_suppression_level=audio.noise_suppression_level,
                        auto_gain=audio.auto_gain,
                        volume_multiplier=audio.volume_multiplier,
                    ),
                    wake_word_phrase=wake_word_phrase,
                )
            )
            port = await asyncio.wait_for(future, timeout)
        finally:
            if self._start_future is future:
                self._start_future = None
        self._pipeline_active = True
        self._stream_port = port
        return port

    async def send_audio(self, data: bytes, data2: bytes | None = None) -> None:
        """Send one microphone PCM chunk over the native API."""
        client = self._require_client()
        if self._stream_port != 0:
            raise VoiceAssistantError("the active pipeline is not using API audio")
        if not data:
            raise ValueError("the primary audio channel cannot be empty")
        if self._multi_channel_audio and not data2:
            raise ValueError("the configured second audio channel cannot be empty")
        if not self._multi_channel_audio and data2 is not None:
            raise ValueError("data2 requires multi_channel_audio=True")
        await client.write_message(
            VoiceAssistantAudio(data=data, data2=data2 if data2 is not None else b"")
        )

    async def finish_audio(self) -> None:
        """Gracefully close the API microphone audio stream."""
        if self._stream_port != 0:
            raise VoiceAssistantError("there is no active API audio stream")
        await self._require_client().write_message(VoiceAssistantAudio(end=True))
        self._stream_port = None

    async def stop(self) -> None:
        """Abort the current Assist pipeline."""
        await self._require_client().write_message(VoiceAssistantRequest(start=False))
        self._stream_port = None
        self._pipeline_active = False

    # Application backend hooks ----------------------------------------
    async def on_client_subscription(self, subscribed: bool, flags: int) -> None:
        """Called when Home Assistant subscribes or unsubscribes."""

    async def on_event(
        self, event_type: VoiceAssistantEventType, data: dict[str, str]
    ) -> None:
        """Handle Assist pipeline state, STT, intent, TTS, or error events."""

    async def on_audio(self, data: bytes, data2: bytes | None, end: bool) -> None:
        """Play raw response audio sent by Home Assistant."""

    async def on_timer(self, timer: VoiceAssistantTimer) -> None:
        """Handle a timer lifecycle update."""

    async def on_announcement(
        self,
        media_id: str,
        text: str,
        preannounce_media_id: str,
        start_conversation: bool,
    ) -> bool:
        """Play an announcement and return whether playback succeeded."""
        return False

    async def on_configuration_request(
        self,
        external_wake_words: tuple[VoiceAssistantExternalWakeWordConfig, ...],
    ) -> VoiceAssistantConfiguration:
        """Return wake word configuration visible to Home Assistant."""
        return self._configuration

    async def on_set_configuration(self, active_wake_words: tuple[str, ...]) -> None:
        """Apply the active wake word IDs selected by Home Assistant."""
        self._configuration = VoiceAssistantConfiguration(
            available_wake_words=self._configuration.available_wake_words,
            active_wake_words=active_wake_words,
            max_active_wake_words=self._configuration.max_active_wake_words,
        )

    # Native API message dispatch --------------------------------------
    async def handle_api_message(
        self, client: "NativeApiConnection", message: "Message"
    ) -> bool:
        if type(message) is SubscribeVoiceAssistantRequest:
            await self._handle_subscription(client, message)
        elif type(message) is VoiceAssistantResponse:
            if client is self._client:
                self._handle_start_response(message)
        elif type(message) is VoiceAssistantEventResponse:
            if client is self._client:
                try:
                    event_type = VoiceAssistantEventType(message.event_type)
                except ValueError:
                    logger.warning(
                        "Ignoring unknown voice assistant event type %s",
                        message.event_type,
                    )
                else:
                    if event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START:
                        self._pipeline_active = True
                    elif event_type in (
                        VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
                        VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END,
                    ):
                        self._stream_port = None
                    elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END:
                        self._stream_port = None
                        self._pipeline_active = False
                    await self.on_event(
                        event_type,
                        {item.name: item.value for item in message.data},
                    )
        elif type(message) is VoiceAssistantAudio:
            if client is self._client:
                await self.on_audio(
                    bytes(message.data),
                    bytes(message.data2) if message.data2 else None,
                    message.end,
                )
        elif type(message) is VoiceAssistantTimerEventResponse:
            if client is self._client:
                try:
                    event_type = VoiceAssistantTimerEventType(message.event_type)
                except ValueError:
                    logger.warning(
                        "Ignoring unknown voice assistant timer event type %s",
                        message.event_type,
                    )
                else:
                    await self.on_timer(
                        VoiceAssistantTimer(
                            event_type=event_type,
                            timer_id=message.timer_id,
                            name=message.name,
                            total_seconds=message.total_seconds,
                            seconds_left=message.seconds_left,
                            is_active=message.is_active,
                        )
                    )
        elif type(message) is VoiceAssistantAnnounceRequest:
            if client is self._client:
                task = asyncio.create_task(self._handle_announcement(client, message))
                self._announcement_tasks.add(task)
                task.add_done_callback(self._announcement_tasks.discard)
        elif type(message) is VoiceAssistantConfigurationRequest:
            await self._handle_configuration_request(client, message)
        elif type(message) is VoiceAssistantSetConfiguration:
            if client is self._client:
                await self.on_set_configuration(tuple(message.active_wake_words))
        else:
            return False
        return True

    async def on_api_client_disconnected(self, client: "NativeApiConnection") -> None:
        if client is not self._client:
            return
        self._client = None
        self._subscription_flags = 0
        self._stream_port = None
        self._pipeline_active = False
        self._subscribed_event.clear()
        self._fail_pending_start(
            VoiceAssistantNotSubscribedError("API client disconnected")
        )
        self._cancel_announcement_tasks()
        await self.on_client_subscription(False, 0)

    async def _handle_subscription(
        self,
        client: "NativeApiConnection",
        message: SubscribeVoiceAssistantRequest,
    ) -> None:
        if message.subscribe:
            if self._client is not None and self._client is not client:
                return
            self._client = client
            self._subscription_flags = message.flags
            self._subscribed_event.set()
            await self.on_client_subscription(True, message.flags)
        elif self._client is client:
            self._client = None
            self._subscription_flags = 0
            self._stream_port = None
            self._pipeline_active = False
            self._subscribed_event.clear()
            self._fail_pending_start(
                VoiceAssistantNotSubscribedError("Home Assistant unsubscribed")
            )
            self._cancel_announcement_tasks()
            await self.on_client_subscription(False, 0)

    def _handle_start_response(self, message: VoiceAssistantResponse) -> None:
        future = self._start_future
        if future is None or future.done():
            return
        if message.error:
            future.set_exception(
                VoiceAssistantStartError("Assist pipeline failed to start")
            )
        else:
            future.set_result(message.port)

    async def _handle_configuration_request(
        self,
        client: "NativeApiConnection",
        message: VoiceAssistantConfigurationRequest,
    ) -> None:
        if client is not self._client:
            await client.write_message(VoiceAssistantConfigurationResponse())
            return
        external = tuple(
            VoiceAssistantExternalWakeWordConfig(
                id=item.id,
                wake_word=item.wake_word,
                trained_languages=tuple(item.trained_languages),
                model_type=item.model_type,
                model_size=item.model_size,
                model_hash=item.model_hash,
                url=item.url,
            )
            for item in message.external_wake_words
        )
        configuration = await self.on_configuration_request(external)
        response = VoiceAssistantConfigurationResponse(
            active_wake_words=configuration.active_wake_words,
            max_active_wake_words=configuration.max_active_wake_words,
        )
        response.available_wake_words.extend(
            VoiceAssistantWakeWordProto(
                id=wake_word.id,
                wake_word=wake_word.wake_word,
                trained_languages=wake_word.trained_languages,
            )
            for wake_word in configuration.available_wake_words
        )
        await client.write_message(response)

    def _require_client(self) -> "NativeApiConnection":
        if self._client is None:
            raise VoiceAssistantNotSubscribedError(
                "Home Assistant has not subscribed to voice assistant"
            )
        return self._client

    def _fail_pending_start(self, error: Exception) -> None:
        if self._start_future is not None and not self._start_future.done():
            self._start_future.set_exception(error)

    async def _handle_announcement(
        self,
        client: "NativeApiConnection",
        message: VoiceAssistantAnnounceRequest,
    ) -> None:
        try:
            success = bool(
                await self.on_announcement(
                    message.media_id,
                    message.text,
                    message.preannounce_media_id,
                    message.start_conversation,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice assistant announcement failed")
            success = False

        if client is self._client:
            try:
                await client.write_message(
                    VoiceAssistantAnnounceFinished(success=success)
                )
            except (ConnectionError, RuntimeError):
                logger.debug(
                    "Voice assistant client disconnected before announcement response"
                )

    def _cancel_announcement_tasks(self) -> None:
        for task in tuple(self._announcement_tasks):
            task.cancel()
