"""UI-agnostic form helpers shared by the TUI (app.py) and the GUI (gui.py).

No textual, customtkinter, or pyserial imports live here — only pure functions
and data over the protocol layer, so every branch is unit-testable headlessly.
"""

from __future__ import annotations

from . import protocol
from .protocol import (
    AirRate, FEC, IODrive, Params, Parity, TransmissionMode, TxPower,
    UartBaud, WakeupTime,
)

# Enum dropdown fields: widget id -> (label, enum class, Params attribute)
ENUM_FIELDS: list[tuple[str, str, type, str]] = [
    ("parity", "UART parity", Parity, "parity"),
    ("uart_baud", "UART baud", UartBaud, "uart_baud"),
    ("air_rate", "Air data rate", AirRate, "air_rate"),
    ("tx_power", "TX power", TxPower, "tx_power"),
    ("fec", "FEC", FEC, "fec"),
    ("wakeup_time", "Wake-up time", WakeupTime, "wakeup_time"),
    ("transmission_mode", "Transmission", TransmissionMode, "transmission_mode"),
    ("io_drive", "IO drive", IODrive, "io_drive"),
]


def enum_options(enum_cls) -> list[tuple[str, int]]:
    return [(m.label, int(m)) for m in enum_cls]


def parse_int(text: str) -> int:
    """Parse a decimal number, or hex if prefixed with 0x."""
    s = text.strip().lower()
    if not s:
        raise ValueError("empty")
    if s.startswith("0x"):
        return int(s[2:], 16)
    return int(s, 10)


def parse_channel(text: str) -> int:
    """Parse a channel number (0..31); accepts decimal or 0x hex."""
    ch = parse_int(text)
    if not (protocol.CHAN_MIN <= ch <= protocol.CHAN_MAX):
        raise ValueError("0..31 only")
    return ch


def parse_address(text: str) -> int:
    """Parse a 16-bit address (0..65535); accepts decimal or 0x hex."""
    addr = parse_int(text)
    if not (0 <= addr <= 0xFFFF):
        raise ValueError("0..65535 only")
    return addr


def channel_calc(text: str) -> tuple[str, bool]:
    """Return (display string, ok). Shows how frequency derives from channel."""
    try:
        chan = parse_channel(text)
    except ValueError as exc:
        return f"invalid: {exc}", False
    mhz = protocol.channel_to_mhz(chan)
    return f"frequency = 410 + {chan} = {mhz} MHz  (0x{chan:02X})", True


def address_calc(text: str) -> tuple[str, bool]:
    """Return (display string, ok). Shows the ADDH/ADDL hex split."""
    try:
        addr = parse_address(text)
    except ValueError as exc:
        return f"invalid: {exc}", False
    hi, lo = (addr >> 8) & 0xFF, addr & 0xFF
    return f"0x{addr:04X} → ADDH=0x{hi:02X}  ADDL=0x{lo:02X}", True


def describe(p: Params) -> str:
    """One-line human-readable summary of a Params object (used in the log)."""
    return (
        f"addr=0x{p.addr_high:02X}{p.addr_low:02X} "
        f"ch=0x{p.channel:02X}({p.frequency_mhz}MHz) "
        f"air={p.air_rate.label} uart={p.uart_baud.label}/{p.parity.label} "
        f"pwr={p.tx_power.label} fec={p.fec.label} "
        f"wake={p.wakeup_time.label} mode={p.transmission_mode.label} io={p.io_drive.label}"
    )
