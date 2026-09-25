"""Expose a physical serial port through the ESPHome serial proxy API.

Run with Python 3.12 and serialx installed:
    python -m examples.serialx_proxy COM3
    python -m examples.serialx_proxy /dev/ttyUSB0
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import uuid

from aioesphomeapi.api_pb2 import SerialProxyConfigureRequest, SerialProxyIdentity
from aioesphomeapi.model import SerialProxyStatus
from serialx import AsyncSerial, Parity, StopBits, async_serial_for_url

from aioesphomeserver import Device, SerialProxy, SerialProxyError

logger = logging.getLogger(__name__)


def device_mac(port: str) -> str:
    digest = hashlib.sha256(f"{uuid.getnode()}:{port}".encode()).digest()
    octets = bytes([(digest[0] & 0xFC) | 0x02, *digest[1:6]])
    return ":".join(f"{value:02X}" for value in octets)


class SerialxProxy(SerialProxy):
    """Forward raw UART bytes between serialx and one Native API subscriber."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        super().__init__(
            port,
            configured_line_states=3,
            identity=SerialProxyIdentity(source=1, product=port),
        )
        self.port = port
        self.baudrate = baudrate
        self.parity = Parity.NONE
        self.stopbits = StopBits.ONE
        self.data_size = 8
        self.flow_control = False
        self._serial: AsyncSerial | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def on_subscribe(self) -> None:
        serial = async_serial_for_url(
            self.port,
            baudrate=self.baudrate,
            parity=self.parity,
            stopbits=self.stopbits,
            byte_size=self.data_size,
            rtscts=self.flow_control,
        )
        await serial.open()
        self._serial = serial
        self._reader_task = asyncio.create_task(self._read_loop(serial))

    async def on_unsubscribe(self) -> None:
        task = self._reader_task
        self._reader_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        serial = self._serial
        self._serial = None
        if serial is not None:
            await serial.close()

    async def on_configure(self, request: SerialProxyConfigureRequest) -> None:
        await self.on_unsubscribe()
        self.baudrate = request.baudrate
        self.parity = (Parity.NONE, Parity.EVEN, Parity.ODD)[request.parity]
        self.stopbits = StopBits(request.stop_bits)
        self.data_size = request.data_size
        self.flow_control = request.flow_control
        await self.on_subscribe()

    async def on_write(self, data: bytes) -> None:
        await self._require_serial().write(data)

    async def on_flush(self) -> SerialProxyStatus:
        await self._require_serial().flush()
        return SerialProxyStatus.OK

    async def on_set_modem_pins(self, line_states: int) -> None:
        await self._require_serial().set_modem_pins(
            rts=bool(line_states & 1), dtr=bool(line_states & 2)
        )

    async def on_get_modem_pins(self) -> int:
        pins = await self._require_serial().get_modem_pins()
        return int(bool(pins.rts.to_bool())) | (int(bool(pins.dtr.to_bool())) << 1)

    async def on_set_mode(self, mode: int) -> None:
        if mode != 0:
            raise SerialProxyError(SerialProxyStatus.NOT_SUPPORTED)

    def _require_serial(self) -> AsyncSerial:
        if self._serial is None:
            raise SerialProxyError(SerialProxyStatus.ERROR, "Serial port is closed")
        return self._serial

    async def _read_loop(self, serial: AsyncSerial) -> None:
        try:
            while data := await serial.read(1024):
                await self.publish_data(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Serial port read failed")


def build_device(port: str, baudrate: int = 115200) -> Device:
    return Device(
        name="python-serial-proxy",
        friendly_name="Python Serial Proxy",
        mac_address=device_mac(port),
        model="Serialx UART gateway",
        project_name="aioesphomeserver.serialx-proxy",
        project_version="1.0.0",
        serial_proxies=[SerialxProxy(port, baudrate)],
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="ESPHome serialx serial proxy")
    parser.add_argument("port", help="COM port or device path")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--api-port", type=int, default=6053)
    args = parser.parse_args()
    await build_device(args.port, args.baudrate).run(
        api_port=args.api_port, web_port=None
    )


if __name__ == "__main__":
    asyncio.run(main())
