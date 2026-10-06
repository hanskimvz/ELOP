"""Payload generation and echo verification.

Payload layout (doc/02-measurement.md 6절):
    [SEQ (4 byte, little-endian)] [PATTERN ... (N-4 byte)]
"""

import random
import struct
from typing import Optional

SEQ_SIZE = 4

STATUS_OK = "OK"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_MISMATCH = "MISMATCH"
STATUS_SEQ_ERROR = "SEQ_ERROR"


class PayloadGenerator:
    FIXED_PATTERNS = ("fixed", "55AA", "walking1", "walking0")

    def __init__(self, size: int, pattern: str, use_seq: bool, seed: Optional[int] = None,
                 fixed_byte: int = 0x5A):
        self.size = size
        self.pattern = pattern
        self.use_seq = use_seq
        self.fixed_byte = fixed_byte & 0xFF
        self._rng = random.Random(seed)
        body_len = size - SEQ_SIZE if use_seq else size
        self._fixed_body = self._make_body(body_len, 0)

    def _make_body(self, length: int, seq: int) -> bytes:
        if self.pattern == "fixed":
            return bytes([self.fixed_byte]) * length
        if self.pattern == "55AA":
            return bytes(0x55 if i % 2 == 0 else 0xAA for i in range(length))
        if self.pattern == "walking1":  # 0x01, 0x02, ... 0x80: 비트 하나만 1
            return bytes(1 << (i % 8) for i in range(length))
        if self.pattern == "walking0":  # 0xFE, 0xFD, ... 0x7F: 비트 하나만 0
            return bytes(0xFF ^ (1 << (i % 8)) for i in range(length))
        if self.pattern == "random":
            return bytes(self._rng.getrandbits(8) for _ in range(length))
        # incrementing: 회차마다 시작값이 달라지도록 seq를 더함
        return bytes((seq + i) & 0xFF for i in range(length))

    def make(self, seq: int) -> bytes:
        body_len = self.size - SEQ_SIZE if self.use_seq else self.size
        if self.pattern in self.FIXED_PATTERNS:
            body = self._fixed_body
        else:
            body = self._make_body(body_len, seq)
        if self.use_seq:
            return struct.pack("<I", seq & 0xFFFFFFFF) + body
        return body


def count_byte_errors(tx: bytes, rx: bytes) -> int:
    """Differing bytes, counting missing bytes as errors."""
    n = min(len(tx), len(rx))
    diff = sum(1 for i in range(n) if tx[i] != rx[i])
    return diff + (len(tx) - n)


def classify(tx: bytes, rx: bytes, use_seq: bool, seq: int) -> str:
    if len(rx) < len(tx):
        return STATUS_TIMEOUT
    if rx == tx:
        return STATUS_OK
    if use_seq:
        rx_seq = struct.unpack("<I", rx[:SEQ_SIZE])[0]
        # 이전 회차의 데이터가 늦게 들어온 경우
        if rx_seq != (seq & 0xFFFFFFFF) and 0 < (seq - rx_seq) & 0xFFFFFFFF < 1000:
            return STATUS_SEQ_ERROR
    return STATUS_MISMATCH
