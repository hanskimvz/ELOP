"""Statistics and theoretical values (doc/02-measurement.md)."""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .config import TestConfig
from .payload import STATUS_MISMATCH, STATUS_OK, STATUS_SEQ_ERROR, STATUS_TIMEOUT

SPEED_OF_LIGHT_M_S = 299_792_458.0
FIBER_INDEX = 1.47


def t_wire_us(payload_size: int, bits_per_byte: float, baudrate: int) -> float:
    return payload_size * bits_per_byte / baudrate * 1e6


def fiber_rtt_us(length_m: float) -> float:
    return 2.0 * length_m * FIBER_INDEX / SPEED_OF_LIGHT_M_S * 1e6


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Linear interpolation percentile, p in [0, 100]."""
    if not sorted_values:
        return math.nan
    k = (len(sorted_values) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_values[int(k)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


@dataclass
class Stats:
    baudrate: int
    count: int
    ok: int
    timeout: int
    mismatch: int
    seq_error: int
    err_bytes: int
    tx_bytes: int
    stale_bytes: int
    min_us: float
    max_us: float
    mean_us: float
    stdev_us: float
    se_us: float
    p50_us: float
    p95_us: float
    p99_us: float
    first_byte_mean_us: float
    t_wire_us: float
    fiber_rtt_us: float

    @property
    def byte_error_rate(self) -> float:
        return self.err_bytes / self.tx_bytes if self.tx_bytes else math.nan

    def as_rows(self):
        """(label, value, unit) rows for display/export."""
        return [
            ("baudrate", self.baudrate, "bps"),
            ("count", self.count, ""),
            ("ok", self.ok, ""),
            ("timeout", self.timeout, ""),
            ("mismatch", self.mismatch, ""),
            ("seq_error", self.seq_error, ""),
            ("err_bytes", self.err_bytes, "byte"),
            ("byte_error_rate", self.byte_error_rate, ""),
            ("stale_bytes", self.stale_bytes, "byte"),
            ("min", self.min_us, "us"),
            ("max", self.max_us, "us"),
            ("mean", self.mean_us, "us"),
            ("stdev", self.stdev_us, "us"),
            ("SE", self.se_us, "us"),
            ("p50", self.p50_us, "us"),
            ("p95", self.p95_us, "us"),
            ("p99", self.p99_us, "us"),
            ("first_byte_mean", self.first_byte_mean_us, "us"),
            ("T_wire (theory)", self.t_wire_us, "us"),
            ("fiber RTT (theory)", self.fiber_rtt_us, "us"),
        ]


def compute(records: List, cfg: TestConfig, baudrate: int) -> Stats:
    """Latency stats over OK records only."""
    lat = sorted(r.latency_us for r in records if r.status == STATUS_OK)
    first = [r.first_byte_us for r in records if r.status == STATUS_OK and r.first_byte_us is not None]
    n = len(lat)

    if n:
        mean = sum(lat) / n
        var = sum((x - mean) ** 2 for x in lat) / (n - 1) if n > 1 else 0.0
        stdev = math.sqrt(var)
        se = stdev / math.sqrt(n)
    else:
        mean = stdev = se = math.nan

    nan = math.nan
    return Stats(
        baudrate=baudrate,
        count=len(records),
        ok=n,
        timeout=sum(1 for r in records if r.status == STATUS_TIMEOUT),
        mismatch=sum(1 for r in records if r.status == STATUS_MISMATCH),
        seq_error=sum(1 for r in records if r.status == STATUS_SEQ_ERROR),
        err_bytes=sum(r.err_bytes for r in records),
        tx_bytes=len(records) * cfg.payload_size,
        stale_bytes=sum(r.stale_bytes for r in records),
        min_us=lat[0] if n else nan,
        max_us=lat[-1] if n else nan,
        mean_us=mean,
        stdev_us=stdev,
        se_us=se,
        p50_us=percentile(lat, 50),
        p95_us=percentile(lat, 95),
        p99_us=percentile(lat, 99),
        first_byte_mean_us=sum(first) / len(first) if first else nan,
        t_wire_us=t_wire_us(cfg.payload_size, cfg.bits_per_byte(), baudrate),
        fiber_rtt_us=fiber_rtt_us(cfg.fiber_length_m) if cfg.setup == "C" else 0.0,
    )


def histogram(values: Sequence[float], bins: int = 50, lo: Optional[float] = None,
              hi: Optional[float] = None):
    """Returns (edges, counts)."""
    if not values:
        return [], []
    lo = min(values) if lo is None else lo
    hi = max(values) if hi is None else hi
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        if lo <= v <= hi:
            idx = min(int((v - lo) / width), bins - 1)
            counts[idx] += 1
    edges = [lo + i * width for i in range(bins + 1)]
    return edges, counts
