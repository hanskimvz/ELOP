"""Measurement settings."""

from dataclasses import asdict, dataclass, field
from typing import List

# 측정 구성 (doc/01-overview.md 5절)
SETUPS = {
    "A": "어댑터 루프백 (CH340 TX-RX 직결)",
    "B": "로컬 RS-422 루프백 (로컬 MAX3490)",
    "C": "광 링크 전체 (원격 배선 루프백)",
    "C0": "광 링크, 짧은 fiber (패치 코드)",
}

PATTERNS = ["incrementing", "fixed", "random", "55AA", "walking1", "walking0"]
READ_MODES = ["poll", "blocking"]
PARITIES = ["N", "E", "O", "M", "S"]
STOPBITS = [1, 1.5, 2]

STANDARD_BAUDRATES = [
    9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
    1000000, 1500000, 2000000, 3000000, 4000000, 6000000, 8000000,
]

DEFAULT_PORT = "COM4"


@dataclass
class TestConfig:
    port: str = DEFAULT_PORT
    channel_no: int = 1
    setup: str = "C"
    fiber_length_m: float = 1000.0

    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    rtscts: bool = False

    payload_size: int = 16
    pattern: str = "incrementing"
    fixed_byte: int = 0x5A  # pattern == "fixed"일 때 값
    use_seq: bool = True

    iterations: int = 1000
    warmup: int = 10
    interval_ms: float = 10.0
    timeout_ms: float = 1000.0
    read_mode: str = "poll"

    # 비어 있으면 baudrate 하나만 측정
    baud_sweep: List[int] = field(default_factory=list)

    high_priority: bool = True
    note: str = ""

    def baudrates(self) -> List[int]:
        return list(self.baud_sweep) if self.baud_sweep else [self.baudrate]

    def bits_per_byte(self) -> float:
        parity_bits = 0 if self.parity == "N" else 1
        return 1 + self.bytesize + parity_bits + self.stopbits

    def validate(self) -> None:
        if self.setup not in SETUPS:
            raise ValueError("unknown setup: {}".format(self.setup))
        if self.pattern not in PATTERNS:
            raise ValueError("unknown pattern: {}".format(self.pattern))
        if self.read_mode not in READ_MODES:
            raise ValueError("unknown read mode: {}".format(self.read_mode))
        if not 0 <= self.fixed_byte <= 0xFF:
            raise ValueError("fixed_byte must be 0x00..0xFF")
        if self.payload_size < 1:
            raise ValueError("payload_size must be >= 1")
        if self.use_seq and self.payload_size < 4:
            raise ValueError("payload_size must be >= 4 when use_seq is on")
        if self.iterations < 1:
            raise ValueError("iterations must be >= 1")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be > 0")
        for b in self.baudrates():
            if b <= 0:
                raise ValueError("invalid baudrate: {}".format(b))

    def to_dict(self) -> dict:
        return asdict(self)
