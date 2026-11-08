"""Application-supplied crash reports, consumed after a successful API send."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aioesphomeapi.api_pb2 import CrashReportCore, CrashReportResponse
from aioesphomeapi.model import CrashReason, CrashReportFlag

if TYPE_CHECKING:
    from aioesphomeserver.native_api_server import NativeApiConnection


class CrashReportStore:
    """Keep one report in RAM; the application supplies diagnostics or persistence.

    Reports use the official protobuf, including per-core backtraces. This class
    does not install exception handlers or generate firmware addresses from Python
    tracebacks. Sending a report clears it only after write_message succeeds.
    """

    def __init__(self, report: CrashReportResponse | None = None) -> None:
        self._report: CrashReportResponse | None = None
        self._send_lock = asyncio.Lock()
        if report is not None:
            self.set_report(report)

    @property
    def flags(self) -> int:
        return self._report.flags if self._report is not None else 0

    def set_report(self, report: CrashReportResponse) -> None:
        """Replace the pending report with a copy, retaining all protobuf fields."""
        if not report.flags & CrashReportFlag.PRESENT:
            raise ValueError("a stored crash report must have the PRESENT flag")
        if report.ByteSize() > 65535 - 20:
            raise ValueError("crash report exceeds the Native API Noise frame limit")
        snapshot = CrashReportResponse()
        snapshot.CopyFrom(report)
        self._report = snapshot

    async def send(self, client: NativeApiConnection) -> None:
        """Serialize consumers; a failed/cancelled send leaves the report available."""
        async with self._send_lock:
            if not client.running:
                return
            report = self._report
            await client.write_message(report if report is not None else CrashReportResponse())
            # A new report may arrive while the previous write waits for drain.
            if client.running and self._report is report:
                self._report = None


__all__ = ["CrashReportStore", "CrashReportCore", "CrashReportResponse", "CrashReason", "CrashReportFlag"]
