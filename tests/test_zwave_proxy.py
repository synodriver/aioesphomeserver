"""Z-Wave subscription ownership and partial-open lifecycle checks."""

import asyncio
from typing import cast

import pytest
from aioesphomeapi.api_pb2 import ZWaveProxyRequest
from aioesphomeapi.model import ZWaveProxyRequestType, ZWaveProxyStatus
from google.protobuf.message import Message

from aioesphomeserver import ZWaveProxy
from aioesphomeserver.native_api_server import NativeApiConnection


class MemoryClient:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def write_message(self, message: Message) -> None:
        self.messages.append(message)


def test_concurrent_zwave_subscribe_opens_backend_once() -> None:
    class BlockingProxy(ZWaveProxy):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.open_count = 0

        async def on_subscribe(self) -> None:
            self.open_count += 1
            self.started.set()
            await self.release.wait()

    async def run() -> None:
        proxy = BlockingProxy()
        first, second = MemoryClient(), MemoryClient()
        first_connection = cast(NativeApiConnection, first)
        second_connection = cast(NativeApiConnection, second)
        request = ZWaveProxyRequest(type=ZWaveProxyRequestType.SUBSCRIBE)
        task = asyncio.create_task(proxy.handle_message(first_connection, request))
        try:
            await asyncio.wait_for(proxy.started.wait(), 2)
            await asyncio.wait_for(proxy.handle_message(second_connection, request), 2)
            assert proxy.owner is first_connection
            assert second.messages[0].status == ZWaveProxyStatus.IN_USE
            proxy.release.set()
            await asyncio.wait_for(task, 2)
            assert proxy.open_count == 1
            assert first.messages[0].status == ZWaveProxyStatus.OK
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await proxy.on_api_client_disconnected(first_connection)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["failure", "cancel"])
def test_failed_zwave_subscribe_closes_partially_opened_backend(cancel: bool) -> None:
    class BlockingProxy(ZWaveProxy):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.opened = False
            self.close_count = 0

        async def on_subscribe(self) -> None:
            self.opened = True
            self.started.set()
            if cancel:
                await asyncio.Event().wait()
            else:
                raise RuntimeError("subscription failed after opening the controller")

        async def on_unsubscribe(self) -> None:
            self.opened = False
            self.close_count += 1

    async def run() -> None:
        proxy = BlockingProxy()
        client = MemoryClient()
        connection = cast(NativeApiConnection, client)
        task = asyncio.create_task(proxy.handle_message(
            connection, ZWaveProxyRequest(type=ZWaveProxyRequestType.SUBSCRIBE)
        ))
        try:
            await asyncio.wait_for(proxy.started.wait(), 2)
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not client.messages
            else:
                await task
                assert client.messages[0].status == ZWaveProxyStatus.NOT_SUPPORTED
            await proxy.on_api_client_disconnected(connection)
            assert proxy.owner is None
            assert not proxy.opened
            assert proxy.close_count == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
