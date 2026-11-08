"""Explicit configuration exports in ESPHome's zstd-compressed EHY1 format."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from aioesphomeapi.api_pb2 import GetYamlResponse

from aioesphomeserver._compression import compress

if TYPE_CHECKING:
    from aioesphomeserver.native_api_server import NativeApiConnection


class StoredYaml:
    """Export only the supplied files; no disk scanning or secret redaction.

    Noise encryption is required unless allow_unencrypted is explicitly enabled.
    File contents may be text or bytes. Paths must be relative and exclude '..'.
    """

    def __init__(
        self, files: Mapping[str, str | bytes], *,
        allow_unencrypted: bool = False, chunk_size: int = 1024,
    ) -> None:
        if not files:
            raise ValueError("stored YAML must contain at least one file")
        if not 1 <= chunk_size <= 60000:
            raise ValueError("YAML chunk_size must be 1..60000")
        envelope = bytearray(b"EHY1" + struct.pack("<I", len(files)))
        for path, content in files.items():
            if (not path or "\0" in path or "\\" in path
                or PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive
                or ".." in PurePosixPath(path).parts):
                raise ValueError("stored YAML paths must be relative without '..'")
            path_bytes = path.encode("utf-8")
            if len(path_bytes) > 65535:
                raise ValueError("stored YAML path exceeds uint16 length")
            data = content.encode("utf-8") if isinstance(content, str) else content
            envelope.extend(struct.pack("<H", len(path_bytes)))
            envelope.extend(path_bytes)
            envelope.extend(struct.pack("<I", len(data)))
            envelope.extend(data)
        self._data = compress(bytes(envelope))
        self.allow_unencrypted = allow_unencrypted
        self.chunk_size = chunk_size

    async def send(self, client: NativeApiConnection) -> None:
        """Stream one transfer with backpressure, owned by the connection task."""
        total_size = len(self._data)
        for offset in range(0, total_size, self.chunk_size):
            end = offset + self.chunk_size
            await client.write_message(GetYamlResponse(
                data=self._data[offset:end], done=end >= total_size,
                total_size=total_size if offset == 0 else 0,
            ))
            await asyncio.sleep(0)


__all__ = ["StoredYaml"]
