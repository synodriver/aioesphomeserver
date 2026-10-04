"""Additional lifecycle cases found while reviewing PR #1."""

import asyncio
from typing import Any, cast
from unittest.mock import patch

import aiohttp
import pytest
from aioesphomeapi import LightColorCapability
from aioesphomeapi.api_pb2 import (
    BluetoothDeviceRequest,
    SerialProxyRequest,
    SubscribeBluetoothConnectionsFreeRequest,
)
from aioesphomeapi.model import BluetoothDeviceRequestType, SerialProxyRequestType

from aioesphomeserver import BluetoothProxy, Device, LightEntity, SerialProxy, WebServer
from aioesphomeserver.native_api_server import NativeApiConnection


class MemoryClient:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def write_message(self, message: Any) -> None:
        self.messages.append(message)


def test_cancelled_bluetooth_connect_releases_reserved_slot() -> None:
    class BlockingProxy(BluetoothProxy):
        def __init__(self) -> None:
            super().__init__(max_connections=1)
            self.started = asyncio.Event()
            self.opened = False

        async def connect(self, address: int, address_type: int, use_cache: bool) -> int:
            self.opened = True
            self.started.set()
            await asyncio.Event().wait()
            return 247

        async def disconnect(self, address: int) -> None:
            self.opened = False

    async def run() -> None:
        proxy = BlockingProxy()
        client = cast(NativeApiConnection, MemoryClient())
        task = asyncio.create_task(
            proxy.handle_api_message(
                client,
                BluetoothDeviceRequest(
                    address=1,
                    request_type=BluetoothDeviceRequestType.CONNECT_V3_WITHOUT_CACHE,
                ),
            )
        )
        try:
            async with asyncio.timeout(2):
                await proxy.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert proxy._connections_free_response().free == 1
            assert not proxy.opened
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_cancelled_slot_broadcast_releases_the_reservation() -> None:
    class SlowClient(MemoryClient):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def write_message(self, message: Any) -> None:
            await super().write_message(message)
            if message.free == 0:
                self.started.set()
                await asyncio.Event().wait()

    async def run() -> None:
        proxy = BluetoothProxy(max_connections=1)
        subscriber = SlowClient()
        await proxy.handle_api_message(
            cast(NativeApiConnection, subscriber),
            SubscribeBluetoothConnectionsFreeRequest(),
        )
        task = asyncio.create_task(
            proxy.handle_api_message(
                cast(NativeApiConnection, MemoryClient()),
                BluetoothDeviceRequest(
                    address=1,
                    request_type=BluetoothDeviceRequestType.CONNECT_V3_WITHOUT_CACHE,
                ),
            )
        )
        try:
            async with asyncio.timeout(2):
                await subscriber.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert proxy._connections_free_response().free == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["failure", "cancel"])
def test_failed_serial_subscribe_closes_partially_opened_backend(cancel: bool) -> None:
    class BlockingProxy(SerialProxy):
        def __init__(self) -> None:
            super().__init__("UART")
            self.started = asyncio.Event()
            self.opened = False

        async def on_subscribe(self) -> None:
            self.opened = True
            self.started.set()
            if cancel:
                await asyncio.Event().wait()
            else:
                raise RuntimeError("subscription failed after opening the port")

        async def on_unsubscribe(self) -> None:
            self.opened = False

    async def run() -> None:
        proxy = BlockingProxy()
        client = cast(NativeApiConnection, MemoryClient())
        task = asyncio.create_task(
            proxy.handle_message(
                client, SerialProxyRequest(instance=0, type=SerialProxyRequestType.SUBSCRIBE)
            )
        )
        try:
            async with asyncio.timeout(2):
                await proxy.started.wait()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            await proxy.on_api_client_disconnected(client)
            assert not proxy.opened
            assert proxy.owner is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["stop", "cancel"])
def test_shutdown_finishes_with_an_open_event_stream(cancel: bool) -> None:
    async def run() -> None:
        device = Device(name="sse-shutdown")
        server = WebServer(name="_web", port=0)
        device.add_entity(server)
        task = asyncio.create_task(server.run())
        response = None
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        try:
            async with asyncio.timeout(3):
                while server._runner is None:
                    await asyncio.sleep(0.01)
            async with aiohttp.ClientSession(connector=connector) as session:
                response = await session.get(f"http://127.0.0.1:{server.port}/events")
                if cancel:
                    task.cancel()
                else:
                    await server.stop()
                done, _ = await asyncio.wait({task}, timeout=2)
                assert task in done, "SSE stream prevented prompt server shutdown"
                if cancel:
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    await task
                assert not server._subscribers
        finally:
            if response is not None:
                response.close()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await connector.close()

    asyncio.run(run())


def test_light_rejects_legacy_capabilities_even_when_numbers_overlap() -> None:
    with pytest.raises(ValueError):
        LightEntity(name="Brightness", color_modes=(LightColorCapability.BRIGHTNESS,))  # type: ignore[arg-type]


def test_bleak_delayed_disconnect_does_not_release_reconnected_address() -> None:
    pytest.importorskip("bleak")
    from examples.bleak_proxy import BleakBluetoothProxy

    class FakeBleakClient:
        def __init__(self, address: str, **kwargs: Any) -> None:
            self.address = address
            self.mtu_size = 247
            self.is_connected = True

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    async def run() -> None:
        address = 0xAABBCCDDEE03
        proxy = BleakBluetoothProxy(max_connections=1)
        first, second = MemoryClient(), MemoryClient()
        with patch("examples.bleak_proxy.BleakClient", FakeBleakClient):
            await proxy.handle_api_message(
                cast(NativeApiConnection, first),
                BluetoothDeviceRequest(
                    address=address,
                    request_type=BluetoothDeviceRequestType.CONNECT_V3_WITHOUT_CACHE,
                ),
            )
            old_client = proxy._clients[address]
            proxy._on_disconnected(old_client)
            # A requested disconnect and reconnect can run before the task
            # scheduled by the peripheral's callback sends its response.
            await proxy.handle_api_message(
                cast(NativeApiConnection, first),
                BluetoothDeviceRequest(
                    address=address, request_type=BluetoothDeviceRequestType.DISCONNECT
                ),
            )
            await proxy.handle_api_message(
                cast(NativeApiConnection, second),
                BluetoothDeviceRequest(
                    address=address,
                    request_type=BluetoothDeviceRequestType.CONNECT_V3_WITHOUT_CACHE,
                ),
            )
            await asyncio.gather(*proxy._disconnect_tasks)
        assert proxy._connection_owners.get(address) is second
        assert address in proxy._clients
        assert second.messages[-1].connected is True

    asyncio.run(run())


def test_bleak_disconnect_during_handshake_keeps_the_slot_reserved() -> None:
    pytest.importorskip("bleak")
    from examples.bleak_proxy import BleakBluetoothProxy

    class PendingBleakClient:
        instances: list["PendingBleakClient"] = []

        def __init__(self, address: str, **kwargs: Any) -> None:
            self.address = address
            self.kwargs = kwargs
            self.mtu_size = 247
            self.is_connected = True
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.instances.append(self)

        async def connect(self) -> None:
            self.started.set()
            if self is self.instances[0]:
                await self.release.wait()

        async def disconnect(self) -> None:
            self.is_connected = False

    async def run() -> None:
        proxy = BleakBluetoothProxy(max_connections=1)
        first, second = MemoryClient(), MemoryClient()
        request = BluetoothDeviceRequest(
            address=1, request_type=BluetoothDeviceRequestType.CONNECT_V3_WITHOUT_CACHE
        )
        with patch("examples.bleak_proxy.BleakClient", PendingBleakClient):
            task = asyncio.create_task(
                proxy.handle_api_message(cast(NativeApiConnection, first), request)
            )
            try:
                async with asyncio.timeout(2):
                    while not PendingBleakClient.instances:
                        await asyncio.sleep(0)
                    backend = PendingBleakClient.instances[0]
                    await backend.started.wait()
                backend.is_connected = False
                backend.kwargs["disconnected_callback"](backend)
                await asyncio.sleep(0)
                await proxy.handle_api_message(cast(NativeApiConnection, second), request)
                assert not second.messages[-1].connected
                assert len(PendingBleakClient.instances) == 1
                backend.release.set()
                await task
                assert not first.messages[-1].connected
                assert proxy._connections_free_response().free == 1
            finally:
                task.cancel()
                await asyncio.gather(task, *proxy._disconnect_tasks, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["failure", "cancel"])
def test_bleak_failed_connect_closes_partial_backend(cancel: bool) -> None:
    pytest.importorskip("bleak")
    from examples.bleak_proxy import BleakBluetoothProxy

    class FakeBleakClient:
        opened = False

        def __init__(self, address: str, **kwargs: Any) -> None:
            self.address = address
            self.started = asyncio.Event()

        async def connect(self) -> None:
            self.opened = True
            self.started.set()
            if cancel:
                await asyncio.Event().wait()
            else:
                raise RuntimeError("connection failed after opening the backend")

        async def disconnect(self) -> None:
            self.opened = False

    async def run() -> None:
        proxy = BleakBluetoothProxy()
        backend = FakeBleakClient("AA:BB:CC:DD:EE:03")
        with patch("examples.bleak_proxy.BleakClient", return_value=backend):
            task = asyncio.create_task(proxy.connect(0xAABBCCDDEE03, 0, True))
            try:
                async with asyncio.timeout(2):
                    await backend.started.wait()
                if cancel:
                    task.cancel()
                expected_error = asyncio.CancelledError if cancel else RuntimeError
                with pytest.raises(expected_error):
                    await task
                assert not backend.opened
                assert not proxy._clients
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
