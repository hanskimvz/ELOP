"""Port discovery and opening."""

import ctypes
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import serial
from serial.tools import list_ports

from .config import TestConfig

if sys.platform == "win32":
    from serial import win32

VID_WCH = 0x1A86   # CH340 등
VID_FTDI = 0x0403  # FT232H, FT4232H 등

# 어댑터별 최대 baudrate (doc/03-ch340.md)
ADAPTER_MAX_BAUD = {
    VID_WCH: 2000000,
    VID_FTDI: 12000000,
}

_PARITY = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}

_STOPBITS = {
    1: serial.STOPBITS_ONE,
    1.5: serial.STOPBITS_ONE_POINT_FIVE,
    2: serial.STOPBITS_TWO,
}


@dataclass
class PortInfo:
    device: str
    description: str
    vid: Optional[int]
    pid: Optional[int]
    serial_number: Optional[str]
    location: Optional[str]

    @property
    def adapter(self) -> str:
        if self.vid == VID_WCH:
            return "CH340"
        if self.vid == VID_FTDI:
            return "FTDI"
        return "other"

    @property
    def max_baud(self) -> Optional[int]:
        return ADAPTER_MAX_BAUD.get(self.vid)

    def label(self) -> str:
        return "{} - {}".format(self.device, self.description)


def list_ports_info() -> List[PortInfo]:
    """All COM ports, known USB-UART adapters first."""
    ports = [
        PortInfo(p.device, p.description, p.vid, p.pid, p.serial_number, p.location)
        for p in list_ports.comports()
    ]
    known = (VID_WCH, VID_FTDI)
    ports.sort(key=lambda p: (p.vid not in known, p.device))
    return ports


def find_port(device: str) -> Optional[PortInfo]:
    for p in list_ports_info():
        if p.device.upper() == device.upper():
            return p
    return None


def comm_status(ser: serial.Serial) -> Tuple[int, int]:
    """(bytes waiting, error flags).

    pyserial의 in_waiting도 내부에서 ClearCommError를 호출하지만 오류 플래그
    (FRAME, OVERRUN, PARITY ...)를 버린다. 같은 호출로 플래그까지 받는다.
    """
    handle = getattr(ser, "_port_handle", None)
    if sys.platform != "win32" or handle is None:
        return ser.in_waiting, 0
    flags = win32.DWORD()
    comstat = win32.COMSTAT()
    if not win32.ClearCommError(handle, ctypes.byref(flags), ctypes.byref(comstat)):
        raise serial.SerialException("ClearCommError failed ({!r})".format(ctypes.WinError()))
    return comstat.cbInQue, flags.value


def open_port(cfg: TestConfig, baudrate: int) -> serial.Serial:
    ser = serial.Serial()
    ser.port = cfg.port
    ser.baudrate = baudrate
    ser.bytesize = cfg.bytesize
    ser.parity = _PARITY[cfg.parity]
    ser.stopbits = _STOPBITS[cfg.stopbits]
    ser.rtscts = cfg.rtscts
    ser.xonxoff = False
    ser.timeout = cfg.timeout_ms / 1000.0
    ser.write_timeout = cfg.timeout_ms / 1000.0
    ser.open()
    if hasattr(ser, "set_buffer_size"):
        # 고속에서 긴 메시지를 받을 때 드라이버 버퍼가 넘치지 않도록
        ser.set_buffer_size(rx_size=1 << 16, tx_size=1 << 16)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser
