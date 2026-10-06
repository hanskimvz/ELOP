"""Measurement loop: send -> receive echo -> timestamp -> verify.

Latency 정의 (doc/02-measurement.md 1절):
    t0      = write() 호출 직전
    t_first = 에코 첫 바이트 수신 시각
    t1      = N 바이트 모두 수신된 시각
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import serial

from .config import TestConfig
from .payload import (
    STATUS_OK,
    STATUS_TIMEOUT,
    PayloadGenerator,
    classify,
    count_byte_errors,
)
from .serial_port import comm_status, open_port

perf_ns = time.perf_counter_ns


@dataclass
class Record:
    channel: int
    baudrate: int
    seq: int
    t_send_ns: int
    first_byte_us: Optional[float]
    latency_us: Optional[float]
    rx_len: int
    err_bytes: int
    stale_bytes: int
    status: str
    comm_flags: int = 0   # Win32 ClearCommError 플래그 (FRAME 0x08, OVERRUN 0x02 ...)
    tx_hex: str = ""      # 오류 메시지만 저장 (에러 분석용)
    rx_hex: str = ""      # 수신 데이터 + 오류 후 늦게 들어온 바이트


# progress(baudrate, done, total, new_records)
ProgressCallback = Callable[[int, int, int, List[Record]], None]


class LatencyTest:
    """Runs one baudrate on one port."""

    def __init__(self, cfg: TestConfig, stop_event: Optional[threading.Event] = None):
        cfg.validate()
        self.cfg = cfg
        self.stop_event = stop_event or threading.Event()

    def run(self, baudrate: int, progress: Optional[ProgressCallback] = None,
            progress_interval_s: float = 0.1) -> List[Record]:
        cfg = self.cfg
        gen = PayloadGenerator(cfg.payload_size, cfg.pattern, cfg.use_seq, fixed_byte=cfg.fixed_byte)
        timeout_ns = int(cfg.timeout_ms * 1e6)
        interval_s = cfg.interval_ms / 1000.0
        # 오류 메시지 뒤에 늦게 들어오는 바이트(추가 바이트 등)를 모으는 시간
        tail_ns = max(1_000_000, int(4 * cfg.bits_per_byte() / baudrate * 1e9))
        records: List[Record] = []
        pending: List[Record] = []
        last_report = time.perf_counter()

        ser = open_port(cfg, baudrate)
        try:
            seq = 0
            for _ in range(cfg.warmup):
                if self.stop_event.is_set():
                    return records
                self._measure_once(ser, gen.make(seq), timeout_ns)
                seq += 1
                self._sleep(interval_s)

            for i in range(cfg.iterations):
                if self.stop_event.is_set():
                    break
                tx = gen.make(seq)
                t0, t_first, t1, rx, stale, flags = self._measure_once(ser, tx, timeout_ns)
                status = classify(tx, rx, cfg.use_seq, seq)
                rec = Record(
                    channel=cfg.channel_no,
                    baudrate=baudrate,
                    seq=i,
                    t_send_ns=t0,
                    first_byte_us=None if t_first is None else (t_first - t0) / 1000.0,
                    latency_us=(t1 - t0) / 1000.0 if status != STATUS_TIMEOUT else None,
                    rx_len=len(rx),
                    err_bytes=0 if status == STATUS_OK else count_byte_errors(tx, rx),
                    stale_bytes=stale,
                    status=status,
                    comm_flags=flags,
                )
                if status != STATUS_OK:
                    tail, tail_flags = self._collect_tail(ser, tail_ns)
                    rec.comm_flags |= tail_flags
                    rec.tx_hex = tx.hex()
                    rec.rx_hex = (rx + tail).hex()
                records.append(rec)
                pending.append(rec)
                seq += 1

                if progress is not None:
                    now = time.perf_counter()
                    if now - last_report >= progress_interval_s or i == cfg.iterations - 1:
                        progress(baudrate, i + 1, cfg.iterations, pending)
                        pending = []
                        last_report = now

                self._sleep(interval_s)
        finally:
            ser.close()

        if progress is not None and pending:
            progress(baudrate, len(records), cfg.iterations, pending)
        return records

    # Windows의 대기 함수는 분해능이 약 15.6 ms라서(timeBeginPeriod가 무시되는 경우도 있음)
    # 이보다 짧은 마지막 구간은 바쁜 대기로 맞춘다.
    _COARSE_SLEEP_MARGIN_S = 0.020

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        deadline = time.perf_counter() + seconds
        coarse = seconds - self._COARSE_SLEEP_MARGIN_S
        if coarse > 0 and self.stop_event.wait(coarse):
            return
        while time.perf_counter() < deadline:
            if self.stop_event.is_set():
                return

    @staticmethod
    def _collect_tail(ser: serial.Serial, duration_ns: int):
        """Bytes arriving shortly after an errored message. Returns (bytes, flags)."""
        buf = bytearray()
        flags = 0
        deadline = perf_ns() + duration_ns
        while perf_ns() < deadline:
            waiting, f = comm_status(ser)
            flags |= f
            if waiting:
                buf += ser.read(waiting)
        return bytes(buf), flags

    def _measure_once(self, ser: serial.Serial, tx: bytes, timeout_ns: int):
        """Returns (t0, t_first, t1, rx, stale_bytes, comm_flags)."""
        stale, _ = comm_status(ser)  # 이전 회차 플래그는 여기서 지움
        if stale:
            ser.read(stale)

        if self.cfg.read_mode == "blocking":
            return self._measure_blocking(ser, tx, stale)
        return self._measure_poll(ser, tx, timeout_ns, stale)

    @staticmethod
    def _measure_poll(ser: serial.Serial, tx: bytes, timeout_ns: int, stale: int):
        n = len(tx)
        buf = bytearray()
        t_first = None
        t_last = None
        flags = 0

        t0 = perf_ns()
        ser.write(tx)
        deadline = t0 + timeout_ns

        # 수신 대기 바이트 폴링: 데이터가 감지된 시각을 기록한다 (read 호출 시간 제외)
        while len(buf) < n:
            waiting, f = comm_status(ser)
            flags |= f
            if waiting:
                now = perf_ns()
                if t_first is None:
                    t_first = now
                t_last = now
                buf += ser.read(min(waiting, n - len(buf)))
            elif perf_ns() > deadline:
                break

        t1 = t_last if len(buf) >= n else perf_ns()
        return t0, t_first, t1, bytes(buf), stale, flags

    @staticmethod
    def _measure_blocking(ser: serial.Serial, tx: bytes, stale: int):
        n = len(tx)
        t0 = perf_ns()
        ser.write(tx)
        first = ser.read(1)
        t_first = perf_ns() if first else None
        rest = ser.read(n - 1) if first and n > 1 else b""
        t1 = perf_ns()
        _, flags = comm_status(ser)
        return t0, t_first, t1, first + rest, stale, flags
