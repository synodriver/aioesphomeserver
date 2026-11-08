"""Zstandard support shared by wizard and stored YAML responses."""

import sys

if sys.version_info >= (3, 14):
    from compression.zstd import compress
else:
    from backports.zstd import compress

__all__ = ["compress"]
