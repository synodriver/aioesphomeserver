import asyncio
from typing import Any

import pytest
from aioesphomeapi import APIClient

from aioesphomeserver import Device, NativeApiServer


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def _start_server() -> tuple[Device, NativeApiServer, asyncio.Task[None]]:
    device = Device(name="homeassistant-actions", mac_address="02:00:00:00:20:01")
    api = NativeApiServer(name="_api", port=0, host="127.0.0.1")
    device.add_entity(api)
    task = asyncio.create_task(api.run())
    await _wait_for(lambda: api.bound_port is not None)
    return device, api, task


async def _stop_server(
    client: APIClient, api: NativeApiServer, task: asyncio.Task[None]
) -> None:
    await client.disconnect()
    await api.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_homeassistant_event_and_service_response() -> None:
    async def run() -> None:
        device, api, server_task = await _start_server()
        client = APIClient("127.0.0.1", api.bound_port or 0, keepalive=60)
        await client.connect()
        calls: list[Any] = []
        client.subscribe_service_calls(calls.append)
        try:
            await _wait_for(
                lambda: any(
                    connection.subscribe_to_homeassistant_services
                    for connection in api._clients
                )
            )
            await device.fire_homeassistant_event(
                "esphome.test_event",
                data={"plain": "value"},
                data_template={"template": "{{ plain }}"},
                variables={"variable": "value"},
            )
            await _wait_for(lambda: len(calls) == 1)
            assert calls[0].service == "esphome.test_event"
            assert calls[0].is_event is True
            assert calls[0].data == {"plain": "value"}
            assert calls[0].data_template == {"template": "{{ plain }}"}
            assert calls[0].variables == {"variable": "value"}

            response_task = asyncio.create_task(
                device.call_homeassistant_service(
                    "light.turn_on",
                    data={"entity_id": "light.test"},
                    wait_for_response=True,
                    response_template="{{ response }}",
                )
            )
            await _wait_for(lambda: len(calls) == 2)
            assert calls[1].wants_response is True
            assert calls[1].response_template == "{{ response }}"
            client.send_homeassistant_action_response(
                calls[1].call_id,
                success=True,
                response_data=b'{"response":"ok"}',
            )
            response = await response_task
            assert response is not None
            assert response.call_id == calls[1].call_id
            assert response.success is True
            assert response.response_data == b'{"response":"ok"}'
        finally:
            await _stop_server(client, api, server_task)

    asyncio.run(run())


def test_homeassistant_action_requires_a_subscription_for_responses() -> None:
    async def run() -> None:
        device, api, server_task = await _start_server()
        try:
            with pytest.raises(RuntimeError, match="not subscribed"):
                await device.call_homeassistant_service(
                    "light.turn_on", wait_for_response=True
                )
        finally:
            await api.stop()
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)

    asyncio.run(run())


def test_homeassistant_action_validates_response_options() -> None:
    async def run() -> None:
        device, api, server_task = await _start_server()
        client = APIClient("127.0.0.1", api.bound_port or 0, keepalive=60)
        await client.connect()
        client.subscribe_service_calls(lambda _call: None)
        try:
            await _wait_for(
                lambda: any(
                    connection.subscribe_to_homeassistant_services
                    for connection in api._clients
                )
            )
            with pytest.raises(ValueError, match="response_template"):
                await device.call_homeassistant_service(
                    "light.turn_on", response_template="{{ value }}"
                )
        finally:
            await _stop_server(client, api, server_task)

    asyncio.run(run())


def test_homeassistant_action_validates_before_subscription_lookup() -> None:
    async def run() -> None:
        device, api, server_task = await _start_server()
        try:
            with pytest.raises(ValueError, match="service name"):
                await device.call_homeassistant_service("")
            with pytest.raises(ValueError, match="timeout"):
                await device.call_homeassistant_service("light.turn_on", timeout=0)
            with pytest.raises(ValueError, match="response_template"):
                await device.call_homeassistant_service(
                    "light.turn_on", response_template="{{ value }}"
                )
        finally:
            await api.stop()
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)

    asyncio.run(run())


def test_pending_homeassistant_action_fails_when_server_stops() -> None:
    async def run() -> None:
        device, api, server_task = await _start_server()
        client = APIClient("127.0.0.1", api.bound_port or 0, keepalive=60)
        await client.connect()
        client.subscribe_service_calls(lambda _call: None)
        try:
            await _wait_for(
                lambda: any(
                    connection.subscribe_to_homeassistant_services
                    for connection in api._clients
                )
            )
            action_task = asyncio.create_task(
                device.call_homeassistant_service(
                    "light.turn_on", wait_for_response=True
                )
            )
            await asyncio.sleep(0)
            await api.stop()
            with pytest.raises(RuntimeError, match="server stopped"):
                await action_task
        finally:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=1)
            except (TimeoutError, ConnectionError, OSError):
                pass
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)

    asyncio.run(run())
