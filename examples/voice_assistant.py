"""Backend-neutral Voice Assistant example."""

from __future__ import annotations

import asyncio

from aioesphomeserver import (
    Device,
    VoiceAssistant,
    VoiceAssistantEventType,
    VoiceAssistantTimer,
    VoiceAssistantWakeWordConfig,
)


class ApplicationVoiceAssistant(VoiceAssistant):
    """Connect the protocol callbacks to the application's audio backend."""

    def __init__(self) -> None:
        super().__init__(
            speaker=True,
            timers=True,
            announcements=True,
            available_wake_words=[
                VoiceAssistantWakeWordConfig("okay_nabu", "Okay Nabu", ("en",))
            ],
            active_wake_words=["okay_nabu"],
            max_active_wake_words=1,
        )

    async def on_event(self, event_type, data) -> None:
        if event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_END:
            print("Recognized:", data.get("text", ""))

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
