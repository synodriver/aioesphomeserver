import asyncio

from aioesphomeapi import APIClient
from aioesphomeapi.model import SupportsResponseType

from aioesphomeserver import Device, NativeApiServer


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def test_user_services_are_discoverable_and_execute_sync_and_async_callbacks():
    asyncio.run(_test_user_services_are_discoverable_and_execute_sync_and_async_callbacks())


async def _test_user_services_are_discoverable_and_execute_sync_and_async_callbacks():
    calls = []

    def sync_service(enabled, count, ratio, label, flags, counts, ratios, labels):
        calls.append((enabled, count, ratio, label, flags, counts, ratios, labels))

    async def async_service(message):
        await asyncio.sleep(0)
        calls.append(message)

    device = Device(name="Services", mac_address="02:00:00:00:00:30")
    sync = device.add_service(
        "set_values",
        sync_service,
        arguments={
            "enabled": bool,
            "count": int,
            "ratio": float,
            "label": str,
            "flags": list[bool],
            "counts": list[int],
            "ratios": list[float],
            "labels": list[str],
        },
    )
    async_service_info = device.add_service(
        "announce",
        async_service,
        arguments={"message": str},
    )
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        _info, _entities, services = await client.device_info_and_list_entities()
        assert [service.name for service in services] == ["set_values", "announce"]
        assert services[0].key == sync.key
        assert services[1].key == async_service_info.key

        await client.execute_service(
            services[0],
            {
                "enabled": True,
                "count": -4,
                "ratio": 1.5,
                "label": "demo",
                "flags": [True, False],
                "counts": [-2, 3],
                "ratios": [0.25, 0.5],
                "labels": ["a", "b"],
            },
        )
        await client.execute_service(services[1], {"message": "hello"})
        await _wait_for(lambda: len(calls) == 2)
        assert calls == [
            (True, -4, 1.5, "demo", [True, False], [-2, 3], [0.25, 0.5], ["a", "b"]),
            "hello",
        ]
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_user_service_optional_response_and_callback_errors():
    asyncio.run(_test_user_service_optional_response_and_callback_errors())


async def _test_user_service_optional_response_and_callback_errors():
    calls = []

    async def service(value):
        calls.append(value)
        if value == "bad":
            raise RuntimeError("expected failure")
        if value == "list":
            return [value]
        if value == "bytes-list":
            return b'["bytes-list"]'
        if value == "bytes-object":
            return b'{"received":"bytes-object"}'
        return {"received": value}

    device = Device(name="Service response", mac_address="02:00:00:00:00:31")
    device.add_service(
        "echo",
        service,
        arguments={"value": str},
        supports_response=SupportsResponseType.OPTIONAL,
    )
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    client = None
    try:
        await _wait_for(lambda: api.bound_port is not None)
        client = APIClient("127.0.0.1", api.bound_port, keepalive=60)
        await client.connect()
        _info, _entities, services = await client.device_info_and_list_entities()
        response = await client.execute_service(
            services[0], {"value": "ok"}, return_response=True
        )
        assert response is not None
        assert response.success is True
        assert response.response_data == b'{"received":"ok"}'

        failed = await client.execute_service(
            services[0], {"value": "bad"}, return_response=True
        )
        assert failed is not None
        assert failed.success is False
        assert failed.error_message == "expected failure"

        for invalid_value in ("list", "bytes-list"):
            invalid = await client.execute_service(
                services[0], {"value": invalid_value}, return_response=True
            )
            assert invalid is not None
            assert invalid.success is False
            assert "JSON object" in invalid.error_message

        raw = await client.execute_service(
            services[0], {"value": "bytes-object"}, return_response=True
        )
        assert raw is not None
        assert raw.success is True
        assert raw.response_data == b'{"received":"bytes-object"}'
        await _wait_for(
            lambda: calls
            == ["ok", "bad", "list", "bytes-list", "bytes-object"]
        )
    finally:
        if client is not None:
            await client.disconnect()
        await api.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
