"""Optional device-initiated TCP connections using the existing native API."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aioesphomeserver.native_api_server import NativeApiConnection, NativeApiServer

__all__ = ["OutgoingConnection"]

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10.0
PRECONDITION_RETRY = 5.0
BACKOFF_MIN = 5.0
BACKOFF_MAX = 300.0


@dataclass(frozen=True)
class OutgoingConnection:
    """Dial a fixed IP or the last key-verified client that requested dial-back.

    Times are in seconds. A learned address lasts for this server instance;
    applications needing persistence can save the server's outgoing_host and
    pass it as host on the next launch. The configured port is used for both
    fixed and learned addresses, never the client's ephemeral source port.
    """

    host: str | None = None
    port: int = 6054
    delay: float = 60.0

    def __post_init__(self) -> None:
        if self.host is not None:
            ipaddress.ip_address(self.host)
        if not 1 <= self.port <= 65535:
            raise ValueError("outgoing port must be between 1 and 65535")
        if not math.isfinite(self.delay) or self.delay < 0:
            raise ValueError("outgoing delay must be finite and non-negative")


class _OutgoingConnectionManager:
    """Own only dialing and retry state; sessions belong to NativeApiServer."""

    def __init__(self, server: NativeApiServer, config: OutgoingConnection) -> None:
        self.server = server
        self.config = config
        self.host = config.host
        self._changed = asyncio.Event()
        self._connect_task: asyncio.Task[
            tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ] | None = None

    def _has_target(self) -> bool:
        return any(
            client.running and client.outgoing_connection_target
            for client in self.server._clients
        )

    def on_target_client(self, client: NativeApiConnection) -> None:
        if self.config.host is None:
            peer = client.writer.get_extra_info("peername")
            if peer:
                address = ipaddress.ip_address(peer[0])
                if isinstance(address, ipaddress.IPv6Address):
                    if address.ipv4_mapped is not None:
                        address = address.ipv4_mapped
                    elif len(peer) == 4 and peer[3] and not address.scope_id:
                        address = ipaddress.IPv6Address(f"{address}%{peer[3]}")
                self.host = str(address)
        # An authenticated inbound target wins over a TCP dial still in flight.
        # A session already handed off is left to the shared connection code.
        if self._connect_task is not None and not self._connect_task.done():
            self._connect_task.cancel()
        self._changed.set()

    def on_client_removed(self, client: NativeApiConnection) -> None:
        if client.outgoing_connection_target:
            self._changed.set()

    @staticmethod
    async def _close_unclaimed_writer(writer: asyncio.StreamWriter) -> None:
        """Reap transports that never reached NativeApiConnection cleanup."""
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    async def run(self) -> None:
        deep_sleep = self.server.attached_device.has_deep_sleep
        idle_delay = BACKOFF_MIN if deep_sleep else self.config.delay
        delay = 0.0 if deep_sleep else self.config.delay
        backoff = BACKOFF_MIN
        while True:
            self._changed.clear()
            if self._has_target():
                backoff = BACKOFF_MIN
                await self._changed.wait()
                delay = idle_delay
                continue
            try:
                async with asyncio.timeout(delay):
                    await self._changed.wait()
            except TimeoutError:
                pass
            else:
                delay = idle_delay
                continue

            device = self.server.attached_device
            if (self.host is None or len(self.server._clients) >= self.server.max_connections
                or device.encryption_key_bytes in (None, bytes(32))):
                delay = PRECONDITION_RETRY
                continue

            streams: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    self._connect_task = asyncio.create_task(
                        asyncio.open_connection(self.host, self.config.port)
                    )
                    streams = await self._connect_task
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                # on_target_client cancelled only the pending TCP dial.
                delay = idle_delay
                continue
            except (OSError, TimeoutError):
                logger.debug("Outgoing native API connection failed; retrying")
            finally:
                # Cancellation can arrive after open_connection produced a
                # writer but before its result was delivered to this task.
                pending = self._connect_task
                self._connect_task = None
                if (streams is None and pending is not None and pending.done()
                    and not pending.cancelled() and pending.exception() is None):
                    await self._close_unclaimed_writer(pending.result()[1])

            if streams is not None:
                reader, writer = streams
                # Recheck after the await: an incoming connection may have won
                # the last slot or declared itself a target while we dialed.
                if (self._has_target()
                    or len(self.server._clients) >= self.server.max_connections
                    or device.encryption_key_bytes in (None, bytes(32))):
                    await self._close_unclaimed_writer(writer)
                    delay = PRECONDITION_RETRY
                    continue
                connection = None
                try:
                    connection = await self.server._handle_connection(
                        reader, writer, outgoing=True
                    )
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise
                    # An awaited backend can be cancelled without the manager
                    # being cancelled. Treat that as a failed session, not stop.
                    logger.debug("Outgoing native API session was cancelled; retrying")
                except Exception:
                    logger.debug("Outgoing native API session failed; retrying")
                if connection is not None and connection.hello_received:
                    backoff = BACKOFF_MIN
                    delay = idle_delay
                    continue
            # Match ESPHome's capped exponential backoff with +/-20% jitter.
            delay = random.uniform(backoff * 0.8, backoff * 1.2)
            backoff = min(backoff * 2, BACKOFF_MAX)
