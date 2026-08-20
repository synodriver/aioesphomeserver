import asyncio

import pytest
from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import (
    SubscribeVoiceAssistantRequest,
    VoiceAssistantAnnounceFinished,
    VoiceAssistantAnnounceRequest,
    VoiceAssistantEventResponse,
    VoiceAssistantResponse,
    VoiceAssistantTimerEventResponse,
)
from aioesphomeapi.model import (
    VoiceAssistantAudioSettings,
    VoiceAssistantEventType,
    VoiceAssistantFeature,
    VoiceAssistantTimerEventType,
)

from aioesphomeserver import (
    Device,
    NativeApiServer,
    VoiceAssistant,
    VoiceAssistantConfiguration,
    VoiceAssistantError,
    VoiceAssistantTimer,
    VoiceAssistantWakeWordConfig,
)


class RecordingVoiceAssistant(VoiceAssistant):
    def __init__(self):
        super().__init__(
            speaker=True,
            timers=True,
            announcements=True,
            start_conversation=True,
            multi_channel_audio=True,
            available_wake_words=[
                VoiceAssistantWakeWordConfig("okay_nabu", "Okay Nabu", ("en",))
            ],
            active_wake_words=["okay_nabu"],
            max_active_wake_words=1,
        )
        self.event = None
        self.audio = None
        self.timer = None
        self.announcement = None
        self.active_wake_words = None

    async def on_event(self, event_type, data):
        self.event = (event_type, data)

    async def on_audio(self, data, data2, end):
        self.audio = (data, data2, end)

    async def on_timer(self, timer: VoiceAssistantTimer):
        self.timer = timer

    async def on_announcement(
        self, media_id, text, preannounce_media_id, start_conversation
    ):
        self.announcement = (
            media_id,
            text,
            preannounce_media_id,
            start_conversation,
        )
        return True

    async def on_set_configuration(self, active_wake_words):
        await super().on_set_configuration(active_wake_words)
        self.active_wake_words = active_wake_words


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


class FakeConnection:
    def __init__(self, error=None):
        self.messages = []
        self.error = error

    async def write_message(self, message):
        if self.error is not None:
            raise self.error
        self.messages.append(message)


def test_voice_assistant_capabilities_match_backend():
    output = VoiceAssistant(output_only=True)
    assert output.feature_flags == int(
        VoiceAssistantFeature.API_AUDIO | VoiceAssistantFeature.ANNOUNCE
    )

    start_conversation = VoiceAssistant(start_conversation=True)
    assert start_conversation.feature_flags & VoiceAssistantFeature.ANNOUNCE
    assert start_conversation.feature_flags & VoiceAssistantFeature.START_CONVERSATION

    with pytest.raises(ValueError, match="output-only"):
        VoiceAssistant(output_only=True, multi_channel_audio=True)


def test_start_write_failure_clears_pending_state():
    asyncio.run(_test_start_write_failure_clears_pending_state())


async def _test_start_write_failure_clears_pending_state():
    voice = VoiceAssistant()
    voice._client = FakeConnection(BrokenPipeError())

    with pytest.raises(BrokenPipeError):
        await voice.start()
    assert voice._start_future is None
    assert voice.is_pipeline_active is False
    assert voice.is_streaming_audio is False


def test_audio_stream_state_and_channel_validation():
    asyncio.run(_test_audio_stream_state_and_channel_validation())


async def _test_audio_stream_state_and_channel_validation():
    voice = VoiceAssistant(multi_channel_audio=True)
    client = FakeConnection()
    await voice.handle_api_message(
        client, SubscribeVoiceAssistantRequest(subscribe=True, flags=1)
    )

    start_task = asyncio.create_task(voice.start())
    await _wait_for(lambda: bool(client.messages))
    await voice.handle_api_message(client, VoiceAssistantResponse(port=0))
    assert await start_task == 0
    assert voice.is_pipeline_active is True
    assert voice.is_streaming_audio is True

    with pytest.raises(VoiceAssistantError, match="already active"):
        await voice.start()
    with pytest.raises(ValueError, match="primary"):
        await voice.send_audio(b"", b"reference")
    with pytest.raises(ValueError, match="second"):
        await voice.send_audio(b"microphone")

    await voice.send_audio(b"microphone", b"reference")
    await voice.finish_audio()
    assert voice.is_streaming_audio is False
    assert voice.is_pipeline_active is True

    await voice.handle_api_message(
        client,
        VoiceAssistantEventResponse(
            event_type=VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END
        ),
    )
    assert voice.is_pipeline_active is False


def test_announcement_does_not_block_protocol_dispatch():
    asyncio.run(_test_announcement_does_not_block_protocol_dispatch())


async def _test_announcement_does_not_block_protocol_dispatch():
    class BlockingAnnouncementVoiceAssistant(VoiceAssistant):
        def __init__(self):
            super().__init__(output_only=True)
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.event = None

        async def on_announcement(self, *args):
            self.started.set()
            await self.release.wait()
            return True

        async def on_event(self, event_type, data):
            self.event = event_type

    voice = BlockingAnnouncementVoiceAssistant()
    client = FakeConnection()
    await voice.handle_api_message(
        client, SubscribeVoiceAssistantRequest(subscribe=True, flags=1)
    )
    await voice.handle_api_message(
        client,
        VoiceAssistantAnnounceRequest(media_id="test.mp3", text="Test"),
    )
    await asyncio.wait_for(voice.started.wait(), 1)

    await voice.handle_api_message(
        client,
        VoiceAssistantEventResponse(
            event_type=VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START
        ),
    )
    assert voice.event == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START
    assert not any(
        isinstance(msg, VoiceAssistantAnnounceFinished) for msg in client.messages
    )

    voice.release.set()
    await _wait_for(
        lambda: any(
            isinstance(msg, VoiceAssistantAnnounceFinished) for msg in client.messages
        )
    )
    finished = next(
        msg
        for msg in client.messages
        if isinstance(msg, VoiceAssistantAnnounceFinished)
    )
    assert finished.success is True


def test_unknown_voice_assistant_enums_are_ignored():
    asyncio.run(_test_unknown_voice_assistant_enums_are_ignored())


async def _test_unknown_voice_assistant_enums_are_ignored():
    voice = RecordingVoiceAssistant()
    client = FakeConnection()
    await voice.handle_api_message(
        client, SubscribeVoiceAssistantRequest(subscribe=True, flags=1)
    )

    assert await voice.handle_api_message(
        client, VoiceAssistantEventResponse(event_type=1234)
    )
    assert await voice.handle_api_message(
        client, VoiceAssistantTimerEventResponse(event_type=1234)
    )
    assert voice.event is None
    assert voice.timer is None


def test_official_client_voice_assistant_round_trip():
    asyncio.run(_test_official_client_voice_assistant_round_trip())


async def _test_official_client_voice_assistant_round_trip():
    voice = RecordingVoiceAssistant()
    device = Device(
        name="Voice Test",
        mac_address="02:00:00:00:00:02",
        voice_assistant=voice,
    )
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    server_task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        info = await client.device_info()
        assert info.voice_assistant_feature_flags == voice.feature_flags

        starts = []
        stops = []
        microphone_audio = []

        async def handle_start(
            conversation_id: str,
            flags: int,
            settings: VoiceAssistantAudioSettings,
            wake_word_phrase: str | None,
        ) -> int:
            starts.append((conversation_id, flags, settings, wake_word_phrase))
            return 0

        async def handle_stop(abort: bool) -> None:
            stops.append(abort)

        async def handle_audio(data: bytes, data2: bytes | None) -> None:
            microphone_audio.append((data, data2))

        unsubscribe = client.subscribe_voice_assistant(
            handle_start=handle_start,
            handle_stop=handle_stop,
            handle_audio=handle_audio,
        )
        await voice.wait_until_subscribed(timeout=2)

        port = await voice.start(conversation_id="conversation-1")
        assert port == 0
        assert starts[0][0] == "conversation-1"

        await voice.send_audio(b"microphone", b"second-channel")
        await _wait_for(lambda: bool(microphone_audio))
        assert microphone_audio == [(b"microphone", b"second-channel")]
        await voice.finish_audio()
        await _wait_for(lambda: bool(stops))
        assert stops[-1] is False

        client.send_voice_assistant_event(
            VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
            {"text": "turn on the light"},
        )
        await _wait_for(lambda: voice.event is not None)
        assert voice.event[1]["text"] == "turn on the light"

        client.send_voice_assistant_audio(b"speaker")
        await _wait_for(lambda: voice.audio is not None)
        assert voice.audio == (b"speaker", None, False)

        client.send_voice_assistant_timer_event(
            VoiceAssistantTimerEventType.VOICE_ASSISTANT_TIMER_STARTED,
            "timer-1",
            "Tea",
            60,
            59,
            True,
        )
        await _wait_for(lambda: voice.timer is not None)
        assert voice.timer.timer_id == "timer-1"

        finished = await client.send_voice_assistant_announcement_await_response(
            "https://example.invalid/announce.mp3",
            timeout=2,
            text="Hello",
            start_conversation=True,
        )
        assert finished.success is True
        assert voice.announcement[1] == "Hello"

        configuration = await client.get_voice_assistant_configuration(timeout=2)
        assert configuration.active_wake_words == ["okay_nabu"]
        assert configuration.available_wake_words[0].wake_word == "Okay Nabu"

        await client.set_voice_assistant_configuration([])
        await _wait_for(lambda: voice.active_wake_words is not None)
        assert voice.active_wake_words == ()

        unsubscribe()
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)
