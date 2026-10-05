"""Voice assistant state follows wire order before start() resumes."""

import asyncio
from typing import cast

from aioesphomeapi.api_pb2 import (
    SubscribeVoiceAssistantRequest,
    VoiceAssistantEventResponse,
    VoiceAssistantResponse,
)
from aioesphomeapi.model import VoiceAssistantEventType
from google.protobuf.message import Message

from aioesphomeserver import VoiceAssistant
from aioesphomeserver.native_api_server import NativeApiConnection


class MemoryClient:
    async def write_message(self, message: Message) -> None:
        pass


def test_run_end_before_start_resumes_keeps_pipeline_stopped() -> None:
    async def run() -> None:
        assistant = VoiceAssistant()
        client = cast(NativeApiConnection, MemoryClient())
        await assistant.handle_api_message(
            client, SubscribeVoiceAssistantRequest(subscribe=True)
        )
        task = asyncio.create_task(assistant.start())
        try:
            await asyncio.sleep(0)
            await assistant.handle_api_message(client, VoiceAssistantResponse(port=0))
            await assistant.handle_api_message(client, VoiceAssistantEventResponse(
                event_type=VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START
            ))
            await assistant.handle_api_message(client, VoiceAssistantEventResponse(
                event_type=VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END
            ))
            assert await task == 0
            assert not assistant.is_pipeline_active
            assert not assistant.is_streaming_audio
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
