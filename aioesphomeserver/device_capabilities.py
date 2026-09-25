"""Official Native API device capability protobuf types."""

from aioesphomeapi.api_pb2 import DeviceCapabilitiesRequest, DeviceCapabilitiesResponse

DEVICE_CAPABILITIES_REQUEST_TYPE = 149
DEVICE_CAPABILITIES_RESPONSE_TYPE = 150

__all__ = [
    "DeviceCapabilitiesRequest",
    "DeviceCapabilitiesResponse",
    "DEVICE_CAPABILITIES_REQUEST_TYPE",
    "DEVICE_CAPABILITIES_RESPONSE_TYPE",
]
