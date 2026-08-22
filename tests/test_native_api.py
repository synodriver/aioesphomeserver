import asyncio
import base64
import logging
from unittest.mock import patch

from aioesphomeapi import APIClient, APIVersion
from aioesphomeapi.api_pb2 import HelloRequest, HelloResponse
from aioesphomeapi.core import APIConnectionError
from aioesphomeapi.model import BluetoothProxyFeature

from aioesphomeserver import (
    BluetoothProxy,
    Device,
    DeviceCapabilitiesRequest,
    DeviceCapabilitiesResponse,
    NativeApiServer,
    SensorEntity,
    SwitchEntity,
)
from aioesphomeserver.device_capabilities import DEVICE_CAPABILITIES_RESPONSE_TYPE
from aioesphomeserver.native_api_server import PROTO_TO_MESSAGE_TYPE, _varuint_to_bytes


async def _read_varuint(reader: asyncio.StreamReader) -> int:
    result = 0
    for bit_position in range(0, 70, 7):
        value = (await reader.readexactly(1))[0]
        result |= (value & 0x7F) << bit_position
        if not value & 0x80:
            return result
    raise ValueError("invalid varuint")


async def _read_plaintext_message(
    reader: asyncio.StreamReader,
) -> tuple[int, bytes]:
    preamble = await _read_varuint(reader)
    assert preamble == 0
    length = await _read_varuint(reader)
    message_type = await _read_varuint(reader)
    return message_type, await reader.readexactly(length)


def _plaintext_frame(message: object) -> bytes:
    payload = message.SerializeToString()
    message_type = PROTO_TO_MESSAGE_TYPE[type(message)]
    return b"".join(
        (
            b"\0",
            _varuint_to_bytes(len(payload)),
            _varuint_to_bytes(message_type),
            payload,
        )
    )


def test_official_client_can_read_entities():
    asyncio.run(_test_official_client_can_read_entities())


async def _test_official_client_can_read_entities():
    device = Device(
        name="Protocol Test",
        mac_address="02:00:00:00:00:01",
        model="Test",
        project_name="protocol-test",
        project_version="1.0",
    )
    device.add_entity(SwitchEntity(name="Relay"))
    device.add_entity(SensorEntity(name="Temperature", unit_of_measurement="C"))
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        assert client.api_version == APIVersion(1, 15)
        info, entities, _services = await client.device_info_and_list_entities()
        assert info.name == "protocol-test"
        assert info.friendly_name == "Protocol Test"
        assert info.model == "Test"
        assert {entity.name for entity in entities} == {"Relay", "Temperature"}
        await client.disconnect()
    finally:
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_device_capabilities_request_returns_bluetooth_proxy_capabilities():
    asyncio.run(
        _test_device_capabilities_request_returns_bluetooth_proxy_capabilities()
    )


async def _test_device_capabilities_request_returns_bluetooth_proxy_capabilities():
    feature_flags = int(
        BluetoothProxyFeature.PASSIVE_SCAN
        | BluetoothProxyFeature.ACTIVE_CONNECTIONS
        | BluetoothProxyFeature.REMOTE_CACHING
        | BluetoothProxyFeature.RAW_ADVERTISEMENTS
        | BluetoothProxyFeature.FEATURE_STATE_AND_MODE
    )
    proxy = BluetoothProxy(
        bluetooth_mac_address="02:00:00:00:20:15",
        feature_flags=feature_flags,
    )
    device = Device(
        name="Capabilities Test",
        mac_address="02:00:00:00:10:15",
        bluetooth_proxy=proxy,
    )
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    writer: asyncio.StreamWriter | None = None
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        reader, writer = await asyncio.open_connection("127.0.0.1", api.bound_port)
        writer.write(
            _plaintext_frame(
                HelloRequest(
                    api_version_major=1,
                    api_version_minor=15,
                    client_info="capabilities-test",
                )
            )
        )
        await writer.drain()
        message_type, payload = await _read_plaintext_message(reader)
        assert message_type == PROTO_TO_MESSAGE_TYPE[HelloResponse]
        hello = HelloResponse()
        hello.ParseFromString(payload)
        assert hello.api_version_minor == 15

        writer.write(_plaintext_frame(DeviceCapabilitiesRequest()))
        await writer.drain()
        message_type, payload = await _read_plaintext_message(reader)
        assert message_type == DEVICE_CAPABILITIES_RESPONSE_TYPE

        response = DeviceCapabilitiesResponse()
        response.ParseFromString(payload)
        assert response.bluetooth_proxy.feature_flags == feature_flags
        assert response.bluetooth_proxy.mac_address == "02:00:00:00:20:15"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_official_client_can_use_noise_encryption():
    asyncio.run(_test_official_client_can_use_noise_encryption())


async def _test_official_client_can_use_noise_encryption():
    raw_key = bytes(range(32))
    encoded_key = base64.b64encode(raw_key).decode("ascii")
    device = Device(
        name="Encrypted Protocol Test",
        mac_address="02:00:00:00:00:02",
        encryption_key=encoded_key,
    )
    device.add_entity(SwitchEntity(name="Encrypted Relay"))
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        client = APIClient(
            "127.0.0.1",
            api.bound_port,
            noise_psk=encoded_key,
            expected_name="encrypted-protocol-test",
            expected_mac="020000000002",
            keepalive=60,
        )
        await client.connect()
        info, entities, _services = await client.device_info_and_list_entities()
        assert info.name == "encrypted-protocol-test"
        assert info.api_encryption_supported is True
        assert info.api_encryption_provisionable is False
        assert [entity.name for entity in entities] == ["Encrypted Relay"]
        await client.disconnect()
    finally:
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_encrypted_server_rejects_wrong_key_and_plaintext():
    asyncio.run(_test_encrypted_server_rejects_wrong_key_and_plaintext())


async def _test_encrypted_server_rejects_wrong_key_and_plaintext():
    encoded_key = base64.b64encode(bytes(range(32))).decode("ascii")
    wrong_key = base64.b64encode(bytes(reversed(range(32)))).decode("ascii")
    device = Device(name="Encrypted", encryption_key=encoded_key)
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        for client in (
            APIClient("127.0.0.1", api.bound_port, noise_psk=wrong_key),
            APIClient("127.0.0.1", api.bound_port),
        ):
            try:
                async with asyncio.timeout(3):
                    await client.connect()
            except APIConnectionError:
                pass
            else:
                raise AssertionError("encrypted server accepted an invalid client")
    finally:
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_encryption_key_validation_and_device_info():
    raw_key = bytes(range(32))
    device = Device(name="Encrypted", encryption_key=raw_key)
    assert device.encryption_key == base64.b64encode(raw_key).decode("ascii")
    assert device.encryption_key_bytes == raw_key

    for invalid_key in ("not-base64", b"too short"):
        try:
            Device(name="Invalid", encryption_key=invalid_key)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid encryption key was accepted")


def test_plaintext_server_rejects_noise_preamble_without_error_traceback(caplog):
    asyncio.run(_test_plaintext_server_rejects_noise_preamble(caplog))


async def _test_plaintext_server_rejects_noise_preamble(caplog):
    device = Device(name="Plaintext")
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    writer = None
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        caplog.set_level(logging.ERROR, logger="aioesphomeserver.native_api_server")
        reader, writer = await asyncio.open_connection("127.0.0.1", api.bound_port)
        writer.write(b"\x01")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(1), timeout=1) == b""
        assert not any(
            record.getMessage() == "Native API connection failed"
            for record in caplog.records
        )
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_plaintext_server_rejects_oversized_frames():
    asyncio.run(_test_plaintext_server_rejects_oversized_frames())


async def _test_plaintext_server_rejects_oversized_frames():
    device = Device(name="Frame limit")
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    writer = None
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        reader, writer = await asyncio.open_connection("127.0.0.1", api.bound_port)
        writer.write(b"\0" + _varuint_to_bytes(65536) + b"\x01")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(1), timeout=1) == b""
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_native_api_limits_idle_and_concurrent_clients():
    asyncio.run(_test_native_api_limits_idle_and_concurrent_clients())


async def _test_native_api_limits_idle_and_concurrent_clients():
    device = Device(name="Connection limits")
    api = NativeApiServer(
        name="_api", port=0, host="127.0.0.1", max_connections=1
    )
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    first_writer = None
    second_writer = None
    try:
        while api.bound_port is None:
            await asyncio.sleep(0)
        with patch("aioesphomeserver.native_api_server.CLIENT_HELLO_TIMEOUT", 0.01):
            first_reader, first_writer = await asyncio.open_connection(
                "127.0.0.1", api.bound_port
            )
            while len(api._clients) != 1:
                await asyncio.sleep(0)
            second_reader, second_writer = await asyncio.open_connection(
                "127.0.0.1", api.bound_port
            )
            assert await asyncio.wait_for(second_reader.read(1), timeout=1) == b""
            assert await asyncio.wait_for(first_reader.read(1), timeout=1) == b""
    finally:
        for writer in (first_writer, second_writer):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
