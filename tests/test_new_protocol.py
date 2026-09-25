"""Interop checks for Native API additions present in aioesphomeapi 46.5."""

import asyncio

from aioesphomeapi import APIClient, APIVersion
from aioesphomeapi.api_pb2 import (
    InfraredRFTransmitCompleteResponse,
    SerialProxyIdentity,
    ZWaveProxyFrame,
    ZWaveProxyRequest,
)
from aioesphomeapi.model import (
    SerialProxyDataReceived,
    SerialProxyMode,
    SerialProxyRequestType,
    SerialProxyStatus,
    ZWaveProxyStatus,
)

from aioesphomeserver import Device, InfraredEntity, NativeApiServer, SerialProxy, ZWaveProxy


class MemorySerial(SerialProxy):
    def __init__(self) -> None:
        super().__init__(
            "Test UART", configured_line_states=3,
            identity=SerialProxyIdentity(source=1, product="Memory UART"),
        )
        self.written = asyncio.Event()
        self.data = b""

    async def on_configure(self, request) -> None:
        self.baudrate = request.baudrate

    async def on_write(self, data: bytes) -> None:
        self.data = data
        self.written.set()

    async def on_flush(self) -> SerialProxyStatus:
        return SerialProxyStatus.OK

    async def on_get_modem_pins(self) -> int:
        return 1

    async def on_set_modem_pins(self, line_states: int) -> None:
        self.line_states = line_states

    async def on_set_mode(self, mode: int) -> None:
        self.mode = mode


class MemoryZWave(ZWaveProxy):
    async def on_frame(self, data: bytes) -> None:
        self.last_frame = data


class MemoryInfrared(InfraredEntity):
    async def on_transmit(self, carrier_frequency, repeat_count, timings, modulation):
        self.last_transmit = (carrier_frequency, repeat_count, timings, modulation)


def test_official_client_new_proxy_features() -> None:
    asyncio.run(_test_official_client_new_proxy_features())


async def _test_official_client_new_proxy_features() -> None:
    serial = MemorySerial()
    zwave = MemoryZWave(home_id=0x12345678)
    infrared = MemoryInfrared(name="IR")
    device = Device("new-protocol", serial_proxies=[serial], zwave_proxy=zwave)
    device.add_entity(infrared)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    clients: list[APIClient] = []
    try:
        await api.wait_started()
        assert api.bound_port is not None
        for _ in range(2):
            client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
            await client.connect()
            clients.append(client)
        owner, other = clients
        assert owner.api_version == APIVersion(1, 18)
        info = await owner.device_info()
        caps = await owner.device_capabilities()
        assert info.serial_proxies[0].name == caps.serial_proxies[0].name == "Test UART"
        assert info.zwave_home_id == caps.zwave_proxy.home_id == 0x12345678
        assert caps.zwave_proxy.feature_flags == zwave.feature_flags

        identity = await owner.serial_proxy_get_identity(0)
        assert identity.product == "Memory UART"
        subscribed = await owner.serial_proxy_subscribe_await_response(0)
        assert subscribed is not None and subscribed.status == SerialProxyStatus.OK
        busy = await other.serial_proxy_subscribe_await_response(0)
        assert busy is not None and busy.status == SerialProxyStatus.PORT_IN_USE
        busy = await other.serial_proxy_configure_await_response(0, 9600)
        assert busy is not None and busy.status == SerialProxyStatus.PORT_IN_USE
        other.serial_proxy_write(0, b"ignored")
        configured = await owner.serial_proxy_configure_await_response(0, 115200)
        assert configured is not None
        assert configured.type == SerialProxyRequestType.CONFIGURE
        assert configured.status == SerialProxyStatus.OK
        assert serial.baudrate == 115200
        mode = await owner.serial_proxy_set_mode_await_response(0, SerialProxyMode.RAW)
        assert mode.status == SerialProxyStatus.OK
        pins_set = await owner.serial_proxy_set_modem_pins_await_response(0, line_states=1)
        assert pins_set is not None and pins_set.status == SerialProxyStatus.OK
        assert (await owner.serial_proxy_get_modem_pins(0)).line_states == 1
        assert (await owner.serial_proxy_flush(0)).status == SerialProxyStatus.OK
        assert (await owner.serial_proxy_get_modem_pins(9)).status == SerialProxyStatus.INVALID_ARGUMENT
        invalid = await owner.serial_proxy_configure_await_response(9, 9600)
        assert invalid is not None and invalid.status == SerialProxyStatus.INVALID_ARGUMENT

        received = asyncio.Event()
        data: list[bytes] = []
        def on_serial_data(value: SerialProxyDataReceived) -> None:
            data.append(value.data)
            received.set()

        unsubscribe = owner.subscribe_serial_proxy_data(on_serial_data)
        owner.serial_proxy_write(0, b"request")
        await asyncio.wait_for(serial.written.wait(), 2)
        assert serial.data == b"request"
        await serial.publish_data(b"reply")
        await asyncio.wait_for(received.wait(), 2)
        assert data == [b"reply"]
        unsubscribe()

        zwave_subscribed = await owner.zwave_proxy_subscribe_await_response()
        assert zwave_subscribed is not None and zwave_subscribed.status == ZWaveProxyStatus.OK
        zwave_busy = await other.zwave_proxy_subscribe_await_response()
        assert zwave_busy is not None and zwave_busy.status == ZWaveProxyStatus.IN_USE
        zwave_unsubscribed = await other.zwave_proxy_unsubscribe_await_response()
        assert zwave_unsubscribed is not None and zwave_unsubscribed.status == ZWaveProxyStatus.OK
        owner._get_connection().send_message(ZWaveProxyFrame(data=b"zwave-request"))
        async with asyncio.timeout(2):
            while not hasattr(zwave, "last_frame"):
                await asyncio.sleep(0)
        assert zwave.last_frame == b"zwave-request"
        home_changed = asyncio.Event()
        home_ids: list[bytes] = []
        def on_home_id(value: ZWaveProxyRequest) -> None:
            home_ids.append(value.data)
            home_changed.set()

        owner._get_connection().add_message_callback(
            on_home_id,
            (ZWaveProxyRequest,),
        )
        await zwave.publish_home_id(0x87654321)
        await asyncio.wait_for(home_changed.wait(), 2)
        assert home_ids == [bytes.fromhex("87654321")]

        completed = asyncio.Event()
        responses: list[InfraredRFTransmitCompleteResponse] = []
        def on_transmit_complete(value: InfraredRFTransmitCompleteResponse) -> None:
            responses.append(value)
            completed.set()

        owner._get_connection().add_message_callback(
            on_transmit_complete,
            (InfraredRFTransmitCompleteResponse,),
        )
        assert infrared.key is not None
        owner.infrared_rf_transmit_raw_timings(infrared.key, 38000, [100, -100])
        await asyncio.wait_for(completed.wait(), 2)
        assert responses[0].success is True
        assert responses[0].key == infrared.key
        assert infrared.last_transmit == (38000, 1, (100, -100), 0)

        await owner.disconnect()
        subscribed = await other.serial_proxy_subscribe_await_response(0)
        assert subscribed is not None and subscribed.status == SerialProxyStatus.OK
        zwave_subscribed = await other.zwave_proxy_subscribe_await_response()
        assert zwave_subscribed is not None and zwave_subscribed.status == ZWaveProxyStatus.OK
    finally:
        for client in clients:
            await client.disconnect()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
