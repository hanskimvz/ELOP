"""Command-line mode.

예)
    python -m app.main --cli --port COM4 --baud 115200 -n 1000
    python -m app.main --cli --sweep 115200,921600,2000000 --setup B
    python -m app.main --compare results/latency_B_....csv results/latency_C_....csv
    python -m app.main --analyze results/latency_C_....csv
"""

import argparse
import sys
import threading

from .compare import compare_files, format_report
from .error_analysis import analyze_records
from .error_analysis import format_report as format_error_report
from .storage import load_csv
from .config import PATTERNS, READ_MODES, SETUPS, TestConfig
from .serial_port import list_ports_info
from .storage import save_results
from .sweep import run_sweep


def build_parser() -> argparse.ArgumentParser:
    d = TestConfig()
    p = argparse.ArgumentParser(prog="app.main", description="UART echo latency test")
    p.add_argument("--cli", action="store_true", help="GUI 없이 측정")
    p.add_argument("--list-ports", action="store_true", help="COM 포트 목록 출력")
    p.add_argument("--compare", nargs=2, metavar=("REF_CSV", "TARGET_CSV"),
                   help="두 결과 파일 비교 (예: B 결과, C 결과)")
    p.add_argument("--analyze", metavar="CSV", help="저장된 결과 파일의 에러 분석")

    p.add_argument("--port", default=d.port)
    p.add_argument("--channel", type=int, default=d.channel_no)
    p.add_argument("--setup", choices=list(SETUPS), default=d.setup)
    p.add_argument("--fiber", type=float, default=d.fiber_length_m, help="fiber 길이 (m)")
    p.add_argument("--baud", type=int, default=d.baudrate)
    p.add_argument("--sweep", default="", help="쉼표로 구분한 baudrate 목록")
    p.add_argument("--parity", default=d.parity, choices=["N", "E", "O", "M", "S"])
    p.add_argument("--stopbits", type=float, default=d.stopbits, choices=[1, 1.5, 2])
    p.add_argument("--rtscts", action="store_true")
    p.add_argument("--size", type=int, default=d.payload_size, help="payload 크기 (byte)")
    p.add_argument("--pattern", choices=PATTERNS, default=d.pattern)
    p.add_argument("--fixed-byte", type=lambda x: int(x, 0), default=d.fixed_byte,
                   help="pattern=fixed일 때 바이트 값 (예: 0x0A)")
    p.add_argument("--no-seq", action="store_true", help="payload에 시퀀스 번호 넣지 않음")
    p.add_argument("-n", "--iterations", type=int, default=d.iterations)
    p.add_argument("--warmup", type=int, default=d.warmup)
    p.add_argument("--interval", type=float, default=d.interval_ms, help="회차 간격 (ms)")
    p.add_argument("--timeout", type=float, default=d.timeout_ms, help="수신 타임아웃 (ms)")
    p.add_argument("--read-mode", choices=READ_MODES, default=d.read_mode)
    p.add_argument("--normal-priority", action="store_true", help="프로세스 우선순위를 올리지 않음")
    p.add_argument("--note", default="")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--no-xlsx", action="store_true", help="CSV만 저장")
    p.add_argument("--out", default=None, help="결과 폴더 (기본: results/)")
    return p


def config_from_args(a) -> TestConfig:
    sweep = [int(x) for x in a.sweep.replace(" ", "").split(",") if x]
    return TestConfig(
        port=a.port,
        channel_no=a.channel,
        setup=a.setup,
        fiber_length_m=a.fiber,
        baudrate=a.baud,
        parity=a.parity,
        stopbits=a.stopbits,
        rtscts=a.rtscts,
        payload_size=a.size,
        pattern=a.pattern,
        fixed_byte=a.fixed_byte,
        use_seq=not a.no_seq,
        iterations=a.iterations,
        warmup=a.warmup,
        interval_ms=a.interval,
        timeout_ms=a.timeout,
        read_mode=a.read_mode,
        baud_sweep=sweep,
        high_priority=not a.normal_priority,
        note=a.note,
    )


def _progress(baud, done, total, _new):
    sys.stdout.write("\r  {} bps: {}/{}".format(baud, done, total))
    sys.stdout.flush()
    if done >= total:
        sys.stdout.write("\n")


def run_cli(a) -> int:
    if a.list_ports:
        for p in list_ports_info():
            print("{:8} {:6} {}".format(p.device, p.adapter, p.description))
        return 0

    if a.analyze:
        _, rows = load_csv(a.analyze)
        print(format_error_report(rows, analyze_records(rows)))
        return 0

    if a.compare:
        rows, ref_meta, tgt_meta = compare_files(*a.compare)
        print(format_report(rows, ref_meta, tgt_meta))
        return 0

    cfg = config_from_args(a)
    cfg.validate()
    stop = threading.Event()
    try:
        result = run_sweep(cfg, stop, progress=_progress, log=lambda m: print("\n" + m))
    except KeyboardInterrupt:
        stop.set()
        print("\n중지됨")
        return 1

    for st in result.stats:
        print("\n[{} bps]".format(st.baudrate))
        for label, value, unit in st.as_rows()[1:]:
            if isinstance(value, float):
                print("  {:20} {:>14.3f} {}".format(label, value, unit))
            else:
                print("  {:20} {:>14} {}".format(label, value, unit))

    if any(st.ok < st.count for st in result.stats):
        print()
        print(format_error_report(result.records, result.errors))

    if not a.no_save and result.records:
        for path in save_results(cfg, result.started, result.records, result.stats,
                                 out_dir=a.out, xlsx=not a.no_xlsx):
            print("saved: {}".format(path))
    return 0
