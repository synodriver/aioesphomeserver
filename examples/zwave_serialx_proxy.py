"""Bridge a Z-Wave Serial API controller to ESPHome Native API using serialx.

Run with Python 3.12 and serialx installed:
    python -m examples.zwave_serialx_proxy COM4
    python -m examples.zwave_serialx_proxy /dev/ttyACM0
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from serialx import AsyncSerial, async_serial_for_url

from aioesphomeserver import Device, ZWaveProxy
from examples.serialx_proxy import device_mac

logger = logging.getLogger(__name__)

SOF = b"\x01"
CONTROL_BYTES = (b"\x06", b"\x15", b"\x18")
GET_NETWORK_IDS = bytes.fromhex("01 03 00 20 DC")


class SerialxZWaveProxy(ZWaveProxy):
    """Pass complete Serial API frames and control bytes to one API client."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self._serial: AsyncSerial | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._query_task: asyncio.Task[None] | None = None

    async def on_subscribe(self) -> None:
        serial = async_serial_for_url(self.port, baudrate=self.baudrate)
        await serial.open()
        self._serial = serial
        self._reader_task = asyncio.create_task(self._read_loop(serial))
        self._query_task = asyncio.create_task(self._query_home_id(serial))

    async def on_unsubscribe(self) -> None:
        tasks = (self._reader_task, self._query_task)
        self._reader_task = self._query_task = None
        for task in tasks:
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)
        serial = self._serial
        self._serial = None
        if serial is not None:
            await serial.close()

    async def on_frame(self, data: bytes) -> None:
        if self._serial is None:
            raise RuntimeError("Z-Wave controller is closed")
        await self._serial.write(data)

    async def _query_home_id(self, serial: AsyncSerial) -> None:
        try:
            await serial.write(GET_NETWORK_IDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Z-Wave Home ID query failed")

    async def _read_loop(self, serial: AsyncSerial) -> None:
        try:
            while True:
                prefix = await serial.readexactly(1)
                if prefix in CONTROL_BYTES:
                    await self.publish_frame(prefix)
                elif prefix == SOF:
                    length_byte = await serial.readexactly(1)
                    length = length_byte[0]
                    if length < 3:
                        continue
                    frame = prefix + length_byte + await serial.readexactly(length)
                    checksum = 0xFF
                    for byte in frame[1:-1]:
                        checksum ^= byte
                    if (
                        length >= 7
                        and frame[2:4] == b"\x01\x20"
                        and frame[-1] == checksum
                    ):
                        await self.publish_home_id(int.from_bytes(frame[4:8], "big"))
                    await self.publish_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Z-Wave controller read failed")


def build_device(port: str, baudrate: int = 115200) -> Device:
    return Device(
        name="python-zwave-proxy",
        friendly_name="Python Z-Wave Proxy",
        mac_address=device_mac(port),
        model="Serialx Z-Wave gateway",
        project_name="aioesphomeserver.zwave-proxy",
        project_version="1.0.0",
        zwave_proxy=SerialxZWaveProxy(port, baudrate),
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="ESPHome serialx Z-Wave proxy")
    parser.add_argument("port", help="Z-Wave controller COM port or device path")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--api-port", type=int, default=6053)
    args = parser.parse_args()
    await build_device(args.port, args.baudrate).run(
        api_port=args.api_port, web_port=None
    )


if __name__ == "__main__":
    asyncio.run(main())
