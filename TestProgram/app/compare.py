"""Compare two result files: mean(C) - mean(B) with standard error.

doc/02-measurement.md 3절. 단일 회차끼리는 뺄 수 없고, 평균끼리만 뺀다.
"""

import math
from dataclasses import dataclass
from typing import List

from .payload import STATUS_OK
from .stats import fiber_rtt_us
from .storage import load_csv


@dataclass
class CompareRow:
    baudrate: int
    n_ref: int
    mean_ref_us: float
    stdev_ref_us: float
    n_target: int
    mean_target_us: float
    stdev_target_us: float
    diff_us: float
    se_us: float


def _mean_stdev(values: List[float]):
    n = len(values)
    if n == 0:
        return math.nan, math.nan
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    return mean, math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))


def _ok_latencies_by_baud(rows):
    out = {}
    for r in rows:
        if r["status"] == STATUS_OK and r["latency_us"] is not None:
            out.setdefault(r["baudrate"], []).append(r["latency_us"])
    return out


def compare_files(ref_path: str, target_path: str):
    """ref = baseline (B or C0), target = C. Returns (rows, ref_meta, target_meta)."""
    ref_meta, ref_rows = load_csv(ref_path)
    tgt_meta, tgt_rows = load_csv(target_path)
    ref = _ok_latencies_by_baud(ref_rows)
    tgt = _ok_latencies_by_baud(tgt_rows)

    rows = []
    for baud in sorted(set(ref) & set(tgt)):
        m_r, s_r = _mean_stdev(ref[baud])
        m_t, s_t = _mean_stdev(tgt[baud])
        n_r, n_t = len(ref[baud]), len(tgt[baud])
        se = math.sqrt(s_r ** 2 / n_r + s_t ** 2 / n_t)
        rows.append(CompareRow(baud, n_r, m_r, s_r, n_t, m_t, s_t, m_t - m_r, se))
    return rows, ref_meta, tgt_meta


def fiber_theory_from_meta(meta) -> float:
    try:
        return fiber_rtt_us(float(meta.get("fiber_length_m", "0")))
    except ValueError:
        return math.nan


def format_report(rows: List[CompareRow], ref_meta, tgt_meta) -> str:
    lines = [
        "reference : {}".format(ref_meta.get("setup", "?")),
        "target    : {}".format(tgt_meta.get("setup", "?")),
        "fiber RTT theory (target fiber length {} m): {:.2f} us".format(
            tgt_meta.get("fiber_length_m", "?"), fiber_theory_from_meta(tgt_meta)),
        "",
        "{:>10} {:>8} {:>12} {:>8} {:>12} {:>12} {:>10}".format(
            "baud", "n_ref", "mean_ref", "n_tgt", "mean_tgt", "diff", "SE"),
    ]
    for r in rows:
        lines.append("{:>10} {:>8} {:>12.2f} {:>8} {:>12.2f} {:>12.2f} {:>10.2f}".format(
            r.baudrate, r.n_ref, r.mean_ref_us, r.n_target, r.mean_target_us, r.diff_us, r.se_us))
    if not rows:
        lines.append("(no common baudrate with OK records)")
    lines.append("")
    lines.append("diff = mean(target) - mean(reference), SE = sqrt(sd_ref^2/n_ref + sd_tgt^2/n_tgt). 단위 us")
    return "\n".join(lines)
