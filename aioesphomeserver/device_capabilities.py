from __future__ import annotations

from dataclasses import dataclass, field

from aioesphomeapi import api_pb2
from aioesphomeapi.core import MESSAGE_TYPE_TO_PROTO

DEVICE_CAPABILITIES_REQUEST_TYPE = 149
DEVICE_CAPABILITIES_RESPONSE_TYPE = 150


def _varuint_to_bytes(value: int) -> bytes:
    if value < 0:
        raise ValueError("varuint cannot encode a negative value")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _read_varuint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    for bit_position in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated protobuf varuint")
        value = data[offset]
        offset += 1
        result |= (value & 0x7F) << bit_position
        if not value & 0x80:
            return result, offset
    raise ValueError("invalid protobuf varuint")


def _key(field_number: int, wire_type: int) -> bytes:
    return _varuint_to_bytes((field_number << 3) | wire_type)


def _length_delimited(field_number: int, payload: bytes) -> bytes:
    return b"".join((_key(field_number, 2), _varuint_to_bytes(len(payload)), payload))


def _skip_field(data: bytes, offset: int, wire_type: int) -> int:
    if wire_type == 0:
        _, offset = _read_varuint(data, offset)
        return offset
    if wire_type == 1:
        return offset + 8
    if wire_type == 2:
        length, offset = _read_varuint(data, offset)
        return offset + length
    if wire_type == 5:
        return offset + 4
    raise ValueError(f"unsupported protobuf wire type: {wire_type}")


@dataclass(slots=True)
class _BluetoothProxyCapabilities:
    feature_flags: int = 0
    mac_address: str = ""

    def SerializeToString(self) -> bytes:
        chunks: list[bytes] = []
        if self.feature_flags:
            chunks.append(_key(1, 0) + _varuint_to_bytes(self.feature_flags))
        if self.mac_address:
            chunks.append(_length_delimited(2, self.mac_address.encode("utf-8")))
        return b"".join(chunks)

    def ParseFromString(self, data: bytes) -> int:
        offset = 0
        while offset < len(data):
            key, offset = _read_varuint(data, offset)
            field_number, wire_type = key >> 3, key & 0x07
            if field_number == 1 and wire_type == 0:
                self.feature_flags, offset = _read_varuint(data, offset)
            elif field_number == 2 and wire_type == 2:
                length, offset = _read_varuint(data, offset)
                self.mac_address = data[offset : offset + length].decode("utf-8")
                offset += length
            else:
                offset = _skip_field(data, offset, wire_type)
        return len(data)


@dataclass(slots=True)
class _VoiceAssistantCapabilities:
    feature_flags: int = 0

    def SerializeToString(self) -> bytes:
        if not self.feature_flags:
            return b""
        return _key(1, 0) + _varuint_to_bytes(self.feature_flags)

    def ParseFromString(self, data: bytes) -> int:
        offset = 0
        while offset < len(data):
            key, offset = _read_varuint(data, offset)
            field_number, wire_type = key >> 3, key & 0x07
            if field_number == 1 and wire_type == 0:
                self.feature_flags, offset = _read_varuint(data, offset)
            else:
                offset = _skip_field(data, offset, wire_type)
        return len(data)


try:
    DeviceCapabilitiesRequest = api_pb2.DeviceCapabilitiesRequest
    DeviceCapabilitiesResponse = api_pb2.DeviceCapabilitiesResponse
except AttributeError:

    class DeviceCapabilitiesRequest:  # type: ignore[no-redef]
        """Fallback for aioesphomeapi versions without API 1.15 capabilities."""

        def SerializeToString(self) -> bytes:
            return b""

        def ParseFromString(self, _data: bytes) -> int:
            return 0

    @dataclass(slots=True)
    class DeviceCapabilitiesResponse:  # type: ignore[no-redef]
        """Fallback protobuf-compatible DeviceCapabilitiesResponse."""

        bluetooth_proxy: _BluetoothProxyCapabilities = field(
            default_factory=_BluetoothProxyCapabilities
        )
        voice_assistant: _VoiceAssistantCapabilities = field(
            default_factory=_VoiceAssistantCapabilities
        )

        def SerializeToString(self) -> bytes:
            chunks: list[bytes] = []
            bluetooth_proxy = self.bluetooth_proxy.SerializeToString()
            if bluetooth_proxy:
                chunks.append(_length_delimited(1, bluetooth_proxy))
            voice_assistant = self.voice_assistant.SerializeToString()
            if voice_assistant:
                chunks.append(_length_delimited(2, voice_assistant))
            return b"".join(chunks)

        def ParseFromString(self, data: bytes) -> int:
            offset = 0
            while offset < len(data):
                key, offset = _read_varuint(data, offset)
                field_number, wire_type = key >> 3, key & 0x07
                if wire_type == 2 and field_number in (1, 2):
                    length, offset = _read_varuint(data, offset)
                    payload = data[offset : offset + length]
                    offset += length
                    if field_number == 1:
                        self.bluetooth_proxy.ParseFromString(payload)
                    else:
                        self.voice_assistant.ParseFromString(payload)
                else:
                    offset = _skip_field(data, offset, wire_type)
            return len(data)


MESSAGE_TYPE_TO_PROTO.setdefault(
    DEVICE_CAPABILITIES_REQUEST_TYPE, DeviceCapabilitiesRequest
)
MESSAGE_TYPE_TO_PROTO.setdefault(
    DEVICE_CAPABILITIES_RESPONSE_TYPE, DeviceCapabilitiesResponse
)
