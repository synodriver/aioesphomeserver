"""Backend-neutral Voice Assistant example."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable

from aioesphomeserver import (
    Device,
    VoiceAssistant,
    VoiceAssistantEventType,
    VoiceAssistantTimer,
    VoiceAssistantWakeWordConfig,
    VoiceAssistantWakeWordAudio,
)


class ApplicationVoiceAssistant(VoiceAssistant):
    """Connect the protocol callbacks to the application's audio backend."""

    def __init__(self) -> None:
        super().__init__(
            speaker=True,
            timers=True,
            announcements=True,
            wake_word_audio=True,
            available_wake_words=[
                VoiceAssistantWakeWordConfig("okay_nabu", "Okay Nabu", ("en",))
            ],
            active_wake_words=["okay_nabu"],
            max_active_wake_words=1,
        )

    async def on_event(self, event_type, data) -> None:
        if event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_END:
            print("Recognized:", data.get("text", ""))
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_WAKE_WORD_REJECTED:
            print("Wake word rejected; resume local detection")

    async def on_audio(self, data: bytes, data2: bytes | None, end: bool) -> None:
        # Feed raw response audio to the application's speaker implementation.
        print(f"Speaker audio: {len(data)} bytes, end={end}")

    async def on_timer(self, timer: VoiceAssistantTimer) -> None:
        print("Timer:", timer)

    async def on_announcement(
        self, media_id, text, preannounce_media_id, start_conversation
    ) -> bool:
        # Play media_id with the application's media player and await completion.
        print("Announcement:", text, media_id)
        return True


async def stream_microphone(voice: VoiceAssistant, chunks) -> None:
    """Start Assist and forward an async iterable of 16-bit PCM chunks."""
    port = await voice.start(use_vad=True)
    if port != 0:
        raise RuntimeError(f"Home Assistant selected legacy UDP audio on port {port}")
    async for chunk in chunks:
        await voice.send_audio(chunk)
    await voice.finish_audio()


async def stream_detected_wake_word(
    voice: VoiceAssistant, buffered_pcm: bytes, live_chunks: AsyncIterable[bytes],
) -> None:
    """Call from a local detector; send buffered PCM before waiting for HA's verdict.

    The audio backend supplies 16 kHz, signed 16-bit mono PCM, including the wake
    word followed by live microphone data. No microphone library is required here.
    """
    detection = VoiceAssistantWakeWordAudio.from_dict({
        "wake_word_id": "okay_nabu", "audio_bytes": len(buffered_pcm),
        "probability": 0.9, "probability_cutoff": 0.7,
    }) if voice.is_wake_word_audio_requested else None
    start = asyncio.create_task(voice.start(wake_word_phrase="Okay Nabu", wake_word=detection))

    async def send_stream() -> None:
        # With negotiated wake word audio this becomes ready before start returns.
        await voice.wait_until_streaming_audio(timeout=10)
        if voice.stream_port != 0:
            raise RuntimeError("This example requires API audio")
        if detection is not None:
            for offset in range(0, len(buffered_pcm), 1024):
                await voice.send_audio(buffered_pcm[offset:offset + 1024])
        async for chunk in live_chunks:
            if start.done():
                await start  # Propagate rejection, disconnect or timeout promptly.
            if not voice.is_streaming_audio:
                break
            await voice.send_audio(chunk)

    sender = asyncio.create_task(send_stream())
    try:
        # Observe a failed start even while the microphone awaits its next chunk.
        await asyncio.gather(start, sender)
        if voice.is_streaming_audio:
            await voice.finish_audio()
    finally:
        sender.cancel()
        start.cancel()
        await asyncio.gather(start, sender, return_exceptions=True)


async def main() -> None:
    voice = ApplicationVoiceAssistant()
    device = Device(
        name="python-voice-assistant",
        friendly_name="Python Voice Assistant",
        mac_address="02:00:00:00:10:03",
        model="Python host",
        voice_assistant=voice,
    )
    await device.run(api_port=6053, web_port=8080)


if __name__ == "__main__":
    asyncio.run(main())
