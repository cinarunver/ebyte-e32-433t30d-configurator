"""Serial transport for the E32 config UART.

The `Transport` protocol keeps the app and protocol layers hardware-agnostic:
they only need `command()`, so tests can supply a fake with no real port.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import serial
from serial.tools import list_ports


class TransportError(RuntimeError):
    """Raised on port-open failures, timeouts, or short reads."""


@dataclass
class PortInfo:
    device: str          # e.g. /dev/ttyUSB0, COM3, /dev/cu.usbserial-XXXX
    description: str
    hwid: str

    @property
    def label(self) -> str:
        desc = self.description if self.description and self.description != "n/a" else ""
        return f"{self.device} — {desc}".rstrip(" —")


def list_serial_ports() -> list[PortInfo]:
    """Cross-platform port enumeration (Linux/macOS/Windows/BSD)."""
    ports = []
    for p in list_ports.comports():
        ports.append(PortInfo(device=p.device, description=p.description or "", hwid=p.hwid or ""))
    return sorted(ports, key=lambda p: p.device)


@runtime_checkable
class Transport(Protocol):
    def command(self, cmd: bytes, expected_len: int, *, retries: int = 1) -> bytes: ...
    def send(self, cmd: bytes) -> None: ...
    def close(self) -> None: ...


class SerialTransport:
    """pyserial-backed transport. The E32 config UART is fixed at 9600 8N1."""

    def __init__(self, port: str, baud: int = 9600, timeout: float = 1.0) -> None:
        self.port = port
        self.timeout = timeout
        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
            )
        except (serial.SerialException, OSError) as exc:
            raise TransportError(f"Could not open {port}: {exc}") from exc

    def send(self, cmd: bytes) -> None:
        try:
            self._ser.reset_input_buffer()
            self._ser.write(cmd)
            self._ser.flush()
        except (serial.SerialException, OSError) as exc:
            raise TransportError(f"Write failed on {self.port}: {exc}") from exc

    def command(self, cmd: bytes, expected_len: int, *, retries: int = 1) -> bytes:
        """Send a command and read exactly `expected_len` bytes.

        The module drives AUX low during power-on self-check and may not answer
        the first request, so one retry is allowed by default.
        """
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                self.send(cmd)
                data = self._ser.read(expected_len)
                if len(data) == expected_len:
                    return data
                last_err = TransportError(
                    f"Timeout: expected {expected_len} bytes, got {len(data)} "
                    f"({data.hex(' ') if data else 'nothing'})"
                )
            except (serial.SerialException, OSError) as exc:
                last_err = TransportError(f"Serial error on {self.port}: {exc}")
            if attempt < retries:
                time.sleep(0.2)
        assert last_err is not None
        raise last_err

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass
