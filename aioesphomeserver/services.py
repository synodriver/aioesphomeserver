"""ESPHome user-defined API actions."""

from __future__ import annotations

import inspect
import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Mapping, get_args, get_origin

from aioesphomeapi.api_pb2 import (
    ExecuteServiceArgument,
    ExecuteServiceRequest,
    ExecuteServiceResponse,
    ListEntitiesServicesResponse,
)

logger = logging.getLogger(__name__)


class ServiceArgType(IntEnum):
    """Argument types supported by ESPHome user-defined actions."""

    BOOL = 0
    INT = 1
    FLOAT = 2
    STRING = 3
    BOOL_ARRAY = 4
    INT_ARRAY = 5
    FLOAT_ARRAY = 6
    STRING_ARRAY = 7


class SupportsResponseType(IntEnum):
    """Response policy for a user-defined action."""

    NONE = 0
    OPTIONAL = 1
    ONLY = 2
    STATUS = 100


ServiceCallback = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ServiceArgument:
    """One action argument and its discovery metadata."""

    type: ServiceArgType | type[Any]
    description: str = ""
    example: str = ""


ServiceArgumentSpec = Mapping[str, ServiceArgType | type[Any] | ServiceArgument]


def _fnv1_hash(value: str) -> int:
    """Match ESPHome's legacy fnv1_hash() used for service keys."""
    result = 2166136261
    for byte in value.encode("utf-8"):
        result = (result * 16777619) & 0xFFFFFFFF
        result ^= byte
    return result


def _argument_type(value: ServiceArgType | type[Any]) -> ServiceArgType:
    if isinstance(value, ServiceArgType):
        return value
    if value is bool:
        return ServiceArgType.BOOL
    if value is int:
        return ServiceArgType.INT
    if value is float:
        return ServiceArgType.FLOAT
    if value is str:
        return ServiceArgType.STRING
    if get_origin(value) is list:
        item_type = get_args(value)
        if len(item_type) == 1:
            array_type = {
                bool: ServiceArgType.BOOL_ARRAY,
                int: ServiceArgType.INT_ARRAY,
                float: ServiceArgType.FLOAT_ARRAY,
                str: ServiceArgType.STRING_ARRAY,
            }.get(item_type[0])
            if array_type is not None:
                return array_type
    raise TypeError(
        "service arguments must use bool, int, float, str, list[T], "
        "or ServiceArgType"
    )


def _response_mode(value: SupportsResponseType | str | int) -> SupportsResponseType:
    if isinstance(value, SupportsResponseType):
        return value
    if isinstance(value, str):
        try:
            return SupportsResponseType[value.upper()]
        except KeyError as err:
            raise ValueError(f"unknown service response mode: {value}") from err
    try:
        return SupportsResponseType(value)
    except ValueError as err:
        raise ValueError(f"unknown service response mode: {value}") from err


def _decode_argument(arg: ExecuteServiceArgument, arg_type: ServiceArgType) -> Any:
    if arg_type is ServiceArgType.BOOL:
        return arg.bool_
    if arg_type is ServiceArgType.INT:
        return arg.int_
    if arg_type is ServiceArgType.FLOAT:
        return arg.float_
    if arg_type is ServiceArgType.STRING:
        return arg.string_
    if arg_type is ServiceArgType.BOOL_ARRAY:
        return list(arg.bool_array)
    if arg_type is ServiceArgType.INT_ARRAY:
        return list(arg.int_array)
    if arg_type is ServiceArgType.FLOAT_ARRAY:
        return list(arg.float_array)
    if arg_type is ServiceArgType.STRING_ARRAY:
        return list(arg.string_array)
    raise AssertionError(f"unsupported service argument type: {arg_type}")


def _encode_response(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        try:
            decoded = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError("service response must be a JSON object") from err
        if not isinstance(decoded, Mapping):
            raise ValueError("service response must be a JSON object")
        return value
    if not isinstance(value, Mapping):
        raise ValueError("service response must be a JSON object")
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(slots=True)
class UserService:
    """One ESPHome user-defined action and its Python callback."""

    name: str
    callback: ServiceCallback
    arguments: ServiceArgumentSpec | None = None
    supports_response: SupportsResponseType | str | int = SupportsResponseType.NONE
    description: str = ""
    key: int = field(init=False)
    _arguments: tuple[tuple[str, ServiceArgType, str, str], ...] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("service name cannot be empty")
        if not callable(self.callback):
            raise TypeError("service callback must be callable")
        if not isinstance(self.description, str):
            raise TypeError("service description must be a string")
        arguments = []
        for name, spec in (self.arguments or {}).items():
            if isinstance(spec, ServiceArgument):
                if not isinstance(spec.description, str) or not isinstance(spec.example, str):
                    raise TypeError("service argument metadata must be strings")
                arguments.append(
                    (name, _argument_type(spec.type), spec.description, spec.example)
                )
            else:
                arguments.append((name, _argument_type(spec), "", ""))
        self._arguments = tuple(arguments)
        if len({name for name, *_ in self._arguments}) != len(self._arguments):
            raise ValueError("service argument names must be unique")
        self.supports_response = _response_mode(self.supports_response)
        self.key = _fnv1_hash(self.name)

    @property
    def argument_types(self) -> tuple[tuple[str, ServiceArgType], ...]:
        return tuple((name, arg_type) for name, arg_type, _, _ in self._arguments)

    def list_entities_response(self) -> ListEntitiesServicesResponse:
        response = ListEntitiesServicesResponse(
            name=self.name,
            key=self.key,
            supports_response=int(self.supports_response),
            description=self.description,
        )
        for name, arg_type, description, example in self._arguments:
            argument = response.args.add()
            argument.name = name
            argument.type = int(arg_type)
            argument.description = description
            argument.example = example
        return response

    def should_respond(self, request: ExecuteServiceRequest) -> bool:
        if self.supports_response is SupportsResponseType.NONE:
            return False
        return self.supports_response is not SupportsResponseType.OPTIONAL or request.return_response

    async def execute(self, request: ExecuteServiceRequest, client: Any) -> None:
        if request.key != self.key or len(request.args) != len(self._arguments):
            return
        values = [
            _decode_argument(arg, arg_type)
            for arg, (_, arg_type, _, _) in zip(request.args, self._arguments)
        ]
        response: ExecuteServiceResponse | None = None
        try:
            if inspect.iscoroutinefunction(self.callback):
                result = self.callback(*values)
            else:
                result = await asyncio.to_thread(self.callback, *values)
            if inspect.isawaitable(result):
                result = await result
            if self.should_respond(request):
                response = ExecuteServiceResponse(
                    call_id=request.call_id,
                    success=True,
                    response_data=(
                        b""
                        if self.supports_response is SupportsResponseType.STATUS
                        else _encode_response(result)
                    ),
                )
        except Exception as err:
            logger.exception("User service %s failed", self.name)
            if self.should_respond(request):
                response = ExecuteServiceResponse(
                    call_id=request.call_id,
                    success=False,
                    error_message=str(err),
                )
        if response is not None:
            await client.write_message(response)


__all__ = ["ServiceArgType", "ServiceArgument", "SupportsResponseType", "UserService"]
