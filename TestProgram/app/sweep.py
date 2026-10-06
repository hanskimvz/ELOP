"""Run the configured baudrate(s) in sequence on one port."""

import datetime
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import serial

from .config import TestConfig
from .error_analysis import ByteError, analyze_records
from .latency_test import LatencyTest, ProgressCallback, Record
from .serial_port import find_port
from .stats import Stats, compute
from .winutil import timing_context

LogCallback = Callable[[str], None]
StatsCallback = Callable[[Stats], None]


@dataclass
class SweepResult:
    started: datetime.datetime
    records: List[Record] = field(default_factory=list)
    stats: List[Stats] = field(default_factory=list)
    errors: List[ByteError] = field(default_factory=list)
    skipped: List[int] = field(default_factory=list)
    stopped: bool = False


def run_sweep(cfg: TestConfig,
              stop_event: Optional[threading.Event] = None,
              progress: Optional[ProgressCallback] = None,
              on_stats: Optional[StatsCallback] = None,
              log: Optional[LogCallback] = None) -> SweepResult:
    stop_event = stop_event or threading.Event()
    log = log or (lambda msg: None)
    result = SweepResult(started=datetime.datetime.now())
    test = LatencyTest(cfg, stop_event)

    port = find_port(cfg.port)
    max_baud = port.max_baud if port else None
    if port:
        log("port {}: {} (adapter {})".format(port.device, port.description, port.adapter))
    else:
        log("port {}: not found in port list".format(cfg.port))

    with timing_context(cfg.high_priority):
        for baud in cfg.baudrates():
            if stop_event.is_set():
                break
            if max_baud is not None and baud > max_baud:
                log("{} bps: 어댑터 최대 {} bps 초과 - 건너뜀".format(baud, max_baud))
                result.skipped.append(baud)
                continue

            log("{} bps: 측정 시작 ({} 회, warmup {})".format(baud, cfg.iterations, cfg.warmup))
            try:
                records = test.run(baud, progress)
            except (serial.SerialException, ValueError) as e:
                log("{} bps: 포트 오류 - {}".format(baud, e))
                result.skipped.append(baud)
                continue

            result.records.extend(records)
            result.errors.extend(analyze_records(records))
            st = compute(records, cfg, baud)
            result.stats.append(st)
            log("{} bps: 완료  ok {}/{}  mean {:.1f} us  stdev {:.1f} us  p99 {:.1f} us".format(
                baud, st.ok, st.count, st.mean_us, st.stdev_us, st.p99_us))
            if on_stats:
                on_stats(st)

    result.stopped = stop_event.is_set()
    return result
