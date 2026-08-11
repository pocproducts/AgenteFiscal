"""RFC 9562 UUIDv7 generator.

Layout (128 bits):
  - 48 bits: Unix timestamp in milliseconds (big-endian)
  - 4 bits: version = 0b0111
  - 12 bits: random (rand_a)
  - 2 bits: variant = 0b10
  - 62 bits: random (rand_b)

Pure stdlib — no external dependencies. Provides time-ordered keys that
sort naturally by insertion time, unlike uuid4 (`gen_random_uuid()`).
"""

from __future__ import annotations

import os
import time
from uuid import UUID

_TS_MASK = (1 << 48) - 1
_RAND_A_MASK = (1 << 12) - 1
_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> UUID:
    """Return a new, time-ordered UUIDv7."""
    ts_ms = int(time.time() * 1000) & _TS_MASK
    rand_a = int.from_bytes(os.urandom(2), 'big') & _RAND_A_MASK
    rand_b = int.from_bytes(os.urandom(8), 'big') & _RAND_B_MASK

    value = (
        (ts_ms << 80)
        | (0b0111 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return UUID(int=value)


__all__ = ['uuid7']