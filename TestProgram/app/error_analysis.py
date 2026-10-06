"""Byte/bit level analysis of echo errors.

비트 번호는 UART 전송 순서를 따른다: bit0 = start bit 바로 다음의 첫 데이터 비트(LSB),
bit7 = 마지막 데이터 비트(MSB). 프레임은 8N1 기준으로 본다.

    idle(1) | start(0) | b0 b1 b2 b3 b4 b5 b6 b7 | stop(1)
"""

import difflib
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

# 오류 종류
KIND_BIT = "BIT"      # 바이트는 도착했지만 값이 다름
KIND_DROP = "DROP"    # 보낸 바이트가 사라짐
KIND_EXTRA = "EXTRA"  # 보내지 않은 바이트가 생김

# BIT 오류 세부 유형
# LATE_kBIT: 수신기가 k비트 늦게 동기됨. rx = (tx >> k) | (상위 k비트 = 1)
#   start bit를 놓치면 다음 첫 0 비트를 start bit로 착각하므로 k = (b0부터 이어지는 1의 개수) + 1
SUB_EARLY1 = "EARLY_1BIT"  # 1비트 일찍 샘플: rx = (tx << 1) & 0xFF (bit0에 start bit)
SUB_SINGLE = "SINGLE_BIT"  # 비트 1개 반전
SUB_MULTI = "MULTI_BIT"    # 비트 여러 개 반전


def late_subtype(k: int) -> str:
    return "LATE_{}BIT".format(k)


SUB_LATE1 = late_subtype(1)
SUB_LATE2 = late_subtype(2)
SUBTYPE_ORDER = [late_subtype(k) for k in range(1, 8)] + [SUB_EARLY1, SUB_SINGLE, SUB_MULTI]

SUBTYPE_LABELS = {late_subtype(k): "{}비트 늦게 동기 (rx = tx>>{} | 0x{:02X})".format(
    k, k, (0xFF << (8 - k)) & 0xFF) for k in range(1, 8)}
SUBTYPE_LABELS.update({
    SUB_EARLY1: "1비트 일찍 동기 (rx = tx<<1)",
    SUB_SINGLE: "단일 비트 반전",
    SUB_MULTI: "다중 비트 반전",
})

# Win32 ClearCommError 플래그
COMM_FLAGS = {
    0x0001: "RXOVER",
    0x0002: "OVERRUN",
    0x0004: "PARITY",
    0x0008: "FRAME",
    0x0010: "BREAK",
}


@dataclass
class ByteError:
    baudrate: int
    seq: int
    kind: str
    pos: int                   # 메시지 내 위치 (DROP/BIT: tx 기준, EXTRA: rx 기준)
    tx: Optional[int]
    rx: Optional[int]
    subtype: str = ""
    flipped_bits: List[int] = field(default_factory=list)
    zero_to_one: int = 0
    one_to_zero: int = 0
    edge_adjacent: int = 0     # 반전된 비트 중 앞/뒤 비트와 값이 다른(엣지 옆) 비트 수

    @property
    def xor(self) -> Optional[int]:
        if self.tx is None or self.rx is None:
            return None
        return self.tx ^ self.rx


def frame_bits(byte: int) -> List[int]:
    """[start, b0..b7, stop] for 8N1."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


def classify_byte(tx: int, rx: int) -> str:
    for k in range(1, 8):
        if rx == ((tx >> k) | ((0xFF << (8 - k)) & 0xFF)):
            return late_subtype(k)
    if rx == ((tx << 1) & 0xFF):
        return SUB_EARLY1
    return SUB_SINGLE if bin(tx ^ rx).count("1") == 1 else SUB_MULTI


def _bit_error(baud: int, seq: int, pos: int, tx: int, rx: int) -> ByteError:
    x = tx ^ rx
    flipped = [i for i in range(8) if (x >> i) & 1]
    f = frame_bits(tx)
    edge = 0
    for i in flipped:
        k = i + 1  # frame index
        if f[k - 1] != f[k] or f[k + 1] != f[k]:
            edge += 1
    return ByteError(
        baudrate=baud, seq=seq, kind=KIND_BIT, pos=pos, tx=tx, rx=rx,
        subtype=classify_byte(tx, rx),
        flipped_bits=flipped,
        zero_to_one=sum(1 for i in flipped if not (tx >> i) & 1),
        one_to_zero=sum(1 for i in flipped if (tx >> i) & 1),
        edge_adjacent=edge,
    )


def analyze_message(baud: int, seq: int, tx: bytes, rx: bytes) -> List[ByteError]:
    """Align rx to tx and classify every differing byte."""
    errors: List[ByteError] = []
    sm = difflib.SequenceMatcher(None, tx, rx, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        n_tx, n_rx = i2 - i1, j2 - j1
        common = min(n_tx, n_rx) if op == "replace" else 0
        for k in range(common):
            errors.append(_bit_error(baud, seq, i1 + k, tx[i1 + k], rx[j1 + k]))
        for k in range(common, n_tx):
            errors.append(ByteError(baud, seq, KIND_DROP, i1 + k, tx[i1 + k], None))
        for k in range(common, n_rx):
            errors.append(ByteError(baud, seq, KIND_EXTRA, j1 + k, None, rx[j1 + k]))
    return errors


def analyze_records(records: Iterable) -> List[ByteError]:
    """Records (or dict rows) with tx_hex/rx_hex filled for non-OK messages."""
    out: List[ByteError] = []
    for r in records:
        get = r.get if isinstance(r, dict) else (lambda k, _r=r: getattr(_r, k))
        tx_hex = get("tx_hex")
        if not tx_hex or get("status") == "OK":
            continue
        tx = bytes.fromhex(tx_hex)
        rx = bytes.fromhex(get("rx_hex") or "")
        out.extend(analyze_message(get("baudrate"), get("seq"), tx, rx))
    return out


def comm_flag_names(flags: int) -> List[str]:
    return [name for bit, name in COMM_FLAGS.items() if flags & bit]


@dataclass
class ErrorSummary:
    baudrate: int
    messages: int
    bad_messages: int
    status_counts: Dict[str, int]
    kind_counts: Dict[str, int]
    subtype_counts: Dict[str, int]
    bit_flips: List[int]           # index = bit 번호
    bit_0to1: List[int]
    bit_1to0: List[int]
    flipped_total: int
    edge_adjacent_total: int
    pos_counts: Dict[int, int]     # 메시지 내 위치별 오류 수
    top_pairs: List                # [((tx, rx), count)]
    comm_flag_counts: Dict[str, int]


def summarize(baud: int, records: List, errors: List[ByteError]) -> ErrorSummary:
    recs = [r for r in records if _get(r, "baudrate") == baud]
    errs = [e for e in errors if e.baudrate == baud]
    bits = [e for e in errs if e.kind == KIND_BIT]

    bit_flips = [0] * 8
    b01 = [0] * 8
    b10 = [0] * 8
    for e in bits:
        for i in e.flipped_bits:
            bit_flips[i] += 1
            if (e.tx >> i) & 1:
                b10[i] += 1
            else:
                b01[i] += 1

    flag_counts: Counter = Counter()
    for r in recs:
        for name in comm_flag_names(int(_get(r, "comm_flags") or 0)):
            flag_counts[name] += 1

    return ErrorSummary(
        baudrate=baud,
        messages=len(recs),
        bad_messages=sum(1 for r in recs if _get(r, "status") != "OK"),
        status_counts=dict(Counter(_get(r, "status") for r in recs)),
        kind_counts=dict(Counter(e.kind for e in errs)),
        subtype_counts=dict(Counter(e.subtype for e in bits)),
        bit_flips=bit_flips,
        bit_0to1=b01,
        bit_1to0=b10,
        flipped_total=sum(bit_flips),
        edge_adjacent_total=sum(e.edge_adjacent for e in bits),
        pos_counts=dict(sorted(Counter(e.pos for e in errs if e.kind != KIND_EXTRA).items())),
        top_pairs=Counter((e.tx, e.rx) for e in bits).most_common(15),
        comm_flag_counts=dict(flag_counts),
    )


def _get(r, key):
    return r.get(key) if isinstance(r, dict) else getattr(r, key)


def _bar(n: int, peak: int, width: int = 30) -> str:
    return "#" * (round(width * n / peak) if peak else 0)


def format_summary(s: ErrorSummary) -> str:
    L = ["[{} bps] 에러 분석".format(s.baudrate)]
    status = ", ".join("{} {}".format(k, v) for k, v in sorted(s.status_counts.items()))
    L.append("  메시지 {} 중 오류 {}  ({})".format(s.messages, s.bad_messages, status))
    if s.bad_messages == 0:
        return "\n".join(L)

    L.append("")
    L.append("  바이트 오류 종류")
    L.append("    값 바뀜 (BIT)     : {}".format(s.kind_counts.get(KIND_BIT, 0)))
    L.append("    누락 (DROP)       : {}".format(s.kind_counts.get(KIND_DROP, 0)))
    L.append("    추가 (EXTRA)      : {}".format(s.kind_counts.get(KIND_EXTRA, 0)))

    if s.subtype_counts:
        L.append("")
        L.append("  값 바뀜 세부 유형")
        for sub in SUBTYPE_ORDER:
            if s.subtype_counts.get(sub):
                L.append("    {:38} {}".format(SUBTYPE_LABELS[sub], s.subtype_counts[sub]))

    if s.flipped_total:
        L.append("")
        L.append("  비트 위치별 반전 (bit0 = start 다음 첫 데이터 비트)")
        peak = max(s.bit_flips)
        for i in range(8):
            L.append("    bit{} {:>6}  (0→1 {:>5}, 1→0 {:>5})  {}".format(
                i, s.bit_flips[i], s.bit_0to1[i], s.bit_1to0[i], _bar(s.bit_flips[i], peak)))
        L.append("    엣지 옆 비트의 반전: {} / {} ({:.0f} %)".format(
            s.edge_adjacent_total, s.flipped_total,
            100.0 * s.edge_adjacent_total / s.flipped_total))

    if s.pos_counts:
        L.append("")
        L.append("  메시지 내 바이트 위치별 오류 (0 = 첫 바이트)")
        peak = max(s.pos_counts.values())
        for pos, n in s.pos_counts.items():
            L.append("    pos{:<4} {:>6}  {}".format(pos, n, _bar(n, peak)))

    if s.top_pairs:
        L.append("")
        L.append("  자주 나온 변환 (tx → rx, 2진수는 MSB(bit7)…LSB(bit0) 순서)")
        for (tx, rx), n in s.top_pairs:
            L.append("    0x{:02X} → 0x{:02X}  {:08b} → {:08b}  {:>5}회  [{}]".format(
                tx, rx, tx, rx, n, classify_byte(tx, rx)))

    L.append("")
    if s.comm_flag_counts:
        L.append("  드라이버 오류 플래그 (메시지 수): " + ", ".join(
            "{} {}".format(k, v) for k, v in sorted(s.comm_flag_counts.items())))
    else:
        L.append("  드라이버 오류 플래그: 없음 (드라이버가 보고하지 않았거나 발생하지 않음)")
    return "\n".join(L)


def format_report(records: List, errors: List[ByteError]) -> str:
    bauds = sorted({_get(r, "baudrate") for r in records})
    return "\n\n".join(format_summary(summarize(b, records, errors)) for b in bauds)
