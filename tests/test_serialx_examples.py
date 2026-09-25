"""Exercise the serialx examples without opening a physical port."""

import asyncio
from typing import Any, cast

import pytest

serialx = pytest.importorskip("serialx")

from aioesphomeapi.api_pb2 import (
    SerialProxyConfigureRequest,
    SerialProxyDataReceived,
    ZWaveProxyFrame,
    ZWaveProxyRequest,
)
from aioesphomeserver.native_api_server import NativeApiConnection

from examples import serialx_proxy, zwave_serialx_proxy


class FakePort:
    def __init__(self, url: str, **options: Any) -> None:
        self.url = url
        self.options = options
        self.opened = False
        self.closed = False
        self.writes: list[bytes] = []
        self.flushed = False
        self.pins: dict[str, bool] = {}
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = b""

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def read(self, _size: int) -> bytes:
        return await self._incoming.get()

    async def readexactly(self, count: int) -> bytes:
        while len(self._buffer) < count:
            self._buffer += await self._incoming.get()
        result, self._buffer = self._buffer[:count], self._buffer[count:]
        return result

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def flush(self) -> None:
        self.flushed = True

    async def set_modem_pins(self, **pins: bool) -> None:
        self.pins = pins

    async def get_modem_pins(self) -> Any:
        return serialx.ModemPins(
            rts=serialx.PinState.HIGH, dtr=serialx.PinState.LOW
        )

    def feed(self, data: bytes) -> None:
        self._incoming.put_nowait(data)


class FakeClient:
    running = True

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def write_message(self, message: Any) -> None:
        self.messages.append(message)


async def wait_for(predicate: Any) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


def test_serialx_proxy_reconfigures_and_forwards_data(monkeypatch: Any) -> None:
    async def run() -> None:
        ports: list[FakePort] = []

        def factory(url: str, **options: Any) -> FakePort:
            port = FakePort(url, **options)
            ports.append(port)
            return port

        monkeypatch.setattr(serialx_proxy, "async_serial_for_url", factory)
        proxy = serialx_proxy.SerialxProxy("COM3")
        client = FakeClient()
        await proxy.on_subscribe()
        proxy.owner = cast(NativeApiConnection, client)
        assert ports[0].opened
        ports[0].feed(b"incoming")
        await wait_for(lambda: bool(client.messages))
        assert isinstance(client.messages[0], SerialProxyDataReceived)
        assert client.messages[0].data == b"incoming"
        await proxy.on_write(b"outgoing")
        assert ports[0].writes == [b"outgoing"]
        await proxy.on_flush()
        assert ports[0].flushed
        await proxy.on_set_modem_pins(1)
        assert ports[0].pins == {"rts": True, "dtr": False}
        assert await proxy.on_get_modem_pins() == 1

        await proxy.on_configure(
            SerialProxyConfigureRequest(
                baudrate=9600, parity=2, stop_bits=2,
                data_size=7, flow_control=True,
            )
        )
        assert ports[0].closed
        assert ports[1].options == {
            "baudrate": 9600, "parity": serialx.Parity.ODD,
            "stopbits": serialx.StopBits.TWO, "byte_size": 7,
            "rtscts": True,
        }
        await proxy.on_unsubscribe()
        assert ports[1].closed
        assert proxy._reader_task is None

    asyncio.run(run())


def test_zwave_serialx_proxy_frames_and_home_id(monkeypatch: Any) -> None:
    async def run() -> None:
        port = FakePort("COM4", baudrate=115200)
        monkeypatch.setattr(
            zwave_serialx_proxy, "async_serial_for_url",
            lambda _url, **_options: port,
        )
        proxy = zwave_serialx_proxy.SerialxZWaveProxy("COM4")
        client = FakeClient()
        await proxy.on_subscribe()
        proxy.owner = cast(NativeApiConnection, client)
        await wait_for(lambda: bool(port.writes))
        assert port.writes == [zwave_serialx_proxy.GET_NETWORK_IDS]

        port.feed(b"\x06")
        frame = bytes.fromhex("01 08 01 20 12 34 56 78 01 DF")
        port.feed(frame)
        await wait_for(lambda: len(client.messages) == 3)
        assert isinstance(client.messages[0], ZWaveProxyFrame)
        assert client.messages[0].data == b"\x06"
        assert isinstance(client.messages[1], ZWaveProxyRequest)
        assert client.messages[1].data == bytes.fromhex("12 34 56 78")
        assert client.messages[2].data == frame
        assert proxy.home_id == 0x12345678

        await proxy.on_frame(b"\x15")
        assert port.writes[-1] == b"\x15"
        await proxy.on_unsubscribe()
        assert port.closed
        assert proxy._reader_task is None

    asyncio.run(run())
