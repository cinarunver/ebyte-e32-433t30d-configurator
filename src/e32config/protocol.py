"""Pure protocol logic for the Ebyte E32-433T30D.

No serial or UI dependencies live here, so every branch is unit-testable without
hardware. Everything is derived from the E32-433T30D user manual v1.9, section 7
(command format) and 7.5 (parameter setting command).

Config commands are issued while the module is in Mode 3 (M0=1, M1=1) over a
9600 8N1 UART.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# ---------------------------------------------------------------------------
# Fixed command frames (sent as-is to the module)
# ---------------------------------------------------------------------------
READ_PARAMS = b"\xC1\xC1\xC1"      # -> C0 ADDH ADDL SPED CHAN OPTION
READ_VERSION = b"\xC3\xC3\xC3"     # -> C3 32 XX YY
RESET = b"\xC4\xC4\xC4"

HEAD_SAVE = 0xC0        # write, persist across power-down
HEAD_TEMP = 0xC2        # write, do not persist
HEAD_READBACK = 0xC0    # module returns params with a 0xC0 head
PARAM_LEN = 6           # C0/C2 + 5 parameter bytes
VERSION_LEN = 4         # C3 32 XX YY


class ProtocolError(ValueError):
    """Raised when a response frame is malformed (bad length or header)."""


# ---------------------------------------------------------------------------
# Enumerations — the integer value is the raw bit-field code from the manual
# ---------------------------------------------------------------------------
class Parity(IntEnum):
    N8N1 = 0b00   # 8N1 (default)
    N8O1 = 0b01   # 8O1
    N8E1 = 0b10   # 8E1
    # 0b11 also means 8N1; normalised to N8N1 on decode.

    @property
    def label(self) -> str:
        return {Parity.N8N1: "8N1", Parity.N8O1: "8O1", Parity.N8E1: "8E1"}[self]


class UartBaud(IntEnum):
    B1200 = 0b000
    B2400 = 0b001
    B4800 = 0b010
    B9600 = 0b011   # default
    B19200 = 0b100
    B38400 = 0b101
    B57600 = 0b110
    B115200 = 0b111

    @property
    def bps(self) -> int:
        return {
            UartBaud.B1200: 1200, UartBaud.B2400: 2400, UartBaud.B4800: 4800,
            UartBaud.B9600: 9600, UartBaud.B19200: 19200, UartBaud.B38400: 38400,
            UartBaud.B57600: 57600, UartBaud.B115200: 115200,
        }[self]

    @property
    def label(self) -> str:
        return str(self.bps)


class AirRate(IntEnum):
    A0_3K = 0b000
    A1_2K = 0b001
    A2_4K = 0b010   # default
    A4_8K = 0b011
    A9_6K = 0b100
    A19_2K = 0b101
    # 0b110 and 0b111 also mean 19.2k; normalised to A19_2K on decode.

    @property
    def bps(self) -> int:
        return {
            AirRate.A0_3K: 300, AirRate.A1_2K: 1200, AirRate.A2_4K: 2400,
            AirRate.A4_8K: 4800, AirRate.A9_6K: 9600, AirRate.A19_2K: 19200,
        }[self]

    @property
    def label(self) -> str:
        return {
            AirRate.A0_3K: "0.3k", AirRate.A1_2K: "1.2k", AirRate.A2_4K: "2.4k",
            AirRate.A4_8K: "4.8k", AirRate.A9_6K: "9.6k", AirRate.A19_2K: "19.2k",
        }[self]


class TransmissionMode(IntEnum):
    TRANSPARENT = 0   # default
    FIXED = 1

    @property
    def label(self) -> str:
        return "Transparent" if self is TransmissionMode.TRANSPARENT else "Fixed"


class IODrive(IntEnum):
    OPEN_COLLECTOR = 0
    PUSH_PULL = 1     # default (push-pull outputs, pull-up inputs)

    @property
    def label(self) -> str:
        return "Open-collector" if self is IODrive.OPEN_COLLECTOR else "Push-pull / pull-up"


class WakeupTime(IntEnum):
    T250 = 0b000   # default
    T500 = 0b001
    T750 = 0b010
    T1000 = 0b011
    T1250 = 0b100
    T1500 = 0b101
    T1750 = 0b110
    T2000 = 0b111

    @property
    def ms(self) -> int:
        return 250 * (self + 1)

    @property
    def label(self) -> str:
        return f"{self.ms}ms"


class TxPower(IntEnum):
    P30 = 0b00   # 30 dBm (default)
    P27 = 0b01   # 27 dBm
    P24 = 0b10   # 24 dBm
    P21 = 0b11   # 21 dBm

    @property
    def dbm(self) -> int:
        return {TxPower.P30: 30, TxPower.P27: 27, TxPower.P24: 24, TxPower.P21: 21}[self]

    @property
    def label(self) -> str:
        return f"{self.dbm}dBm"


class FEC(IntEnum):
    OFF = 0
    ON = 1   # manual prose calls this the default; see spec note on 0x40

    @property
    def label(self) -> str:
        return "On" if self is FEC.ON else "Off"


# ---------------------------------------------------------------------------
# Channel <-> frequency helpers (CHAN bits 4-0; freq = 410 + CHAN MHz)
# ---------------------------------------------------------------------------
CHAN_MIN = 0x00
CHAN_MAX = 0x1F  # 410..441 MHz


def channel_to_mhz(chan: int) -> int:
    return 410 + chan


def mhz_to_channel(mhz: int) -> int:
    chan = mhz - 410
    if not (CHAN_MIN <= chan <= CHAN_MAX):
        raise ProtocolError(f"Frequency {mhz} MHz out of range (410-441 MHz)")
    return chan


# ---------------------------------------------------------------------------
# Parameter container
# ---------------------------------------------------------------------------
@dataclass
class Params:
    """Decoded module configuration. Fields map 1:1 to the manual's tables."""

    addr_high: int = 0x00
    addr_low: int = 0x00
    parity: Parity = Parity.N8N1
    uart_baud: UartBaud = UartBaud.B9600
    air_rate: AirRate = AirRate.A2_4K
    channel: int = 0x17  # 433 MHz
    transmission_mode: TransmissionMode = TransmissionMode.TRANSPARENT
    io_drive: IODrive = IODrive.PUSH_PULL
    wakeup_time: WakeupTime = WakeupTime.T250
    fec: FEC = FEC.ON
    tx_power: TxPower = TxPower.P30

    @property
    def frequency_mhz(self) -> int:
        return channel_to_mhz(self.channel)

    @property
    def address(self) -> int:
        return (self.addr_high << 8) | self.addr_low


# ---------------------------------------------------------------------------
# Decode / encode
# ---------------------------------------------------------------------------
def _decode_sped(sped: int) -> tuple[Parity, UartBaud, AirRate]:
    parity_bits = (sped >> 6) & 0b11
    parity = Parity.N8N1 if parity_bits == 0b11 else Parity(parity_bits)

    baud = UartBaud((sped >> 3) & 0b111)

    air_bits = sped & 0b111
    air = AirRate.A19_2K if air_bits >= 0b101 else AirRate(air_bits)
    return parity, baud, air


def _decode_option(option: int) -> tuple[TransmissionMode, IODrive, WakeupTime, FEC, TxPower]:
    mode = TransmissionMode((option >> 7) & 0b1)
    io = IODrive((option >> 6) & 0b1)
    wakeup = WakeupTime((option >> 3) & 0b111)
    fec = FEC((option >> 2) & 0b1)
    power = TxPower(option & 0b11)
    return mode, io, wakeup, fec, power


def decode_params(data: bytes) -> Params:
    """Parse a 6-byte C0/C1 response into a Params object."""
    if len(data) != PARAM_LEN:
        raise ProtocolError(f"Expected {PARAM_LEN} bytes, got {len(data)}: {data.hex(' ')}")
    if data[0] not in (HEAD_SAVE, HEAD_TEMP):
        raise ProtocolError(f"Unexpected head byte 0x{data[0]:02X} (want 0xC0/0xC2)")

    parity, baud, air = _decode_sped(data[3])
    mode, io, wakeup, fec, power = _decode_option(data[5])
    return Params(
        addr_high=data[1],
        addr_low=data[2],
        parity=parity,
        uart_baud=baud,
        air_rate=air,
        channel=data[4] & 0b11111,
        transmission_mode=mode,
        io_drive=io,
        wakeup_time=wakeup,
        fec=fec,
        tx_power=power,
    )


def encode_params(p: Params, save: bool = True) -> bytes:
    """Build a 6-byte C0 (save) or C2 (temp) write frame from Params."""
    head = HEAD_SAVE if save else HEAD_TEMP
    sped = (int(p.parity) << 6) | (int(p.uart_baud) << 3) | int(p.air_rate)
    chan = p.channel & 0b11111
    option = (
        (int(p.transmission_mode) << 7)
        | (int(p.io_drive) << 6)
        | (int(p.wakeup_time) << 3)
        | (int(p.fec) << 2)
        | int(p.tx_power)
    )
    return bytes([head, p.addr_high & 0xFF, p.addr_low & 0xFF, sped & 0xFF, chan, option & 0xFF])


# ---------------------------------------------------------------------------
# Version response
# ---------------------------------------------------------------------------
_IFACE_NAMES = {0x1: "TTL", 0x4: "RS232", 0x8: "RS485"}


@dataclass
class Version:
    model: int          # 0x32 for this family
    version: int        # raw version byte
    interface: str      # "TTL" / "RS232" / "RS485" / "unknown"
    raw_iface_power: int

    @property
    def label(self) -> str:
        return f"model 0x{self.model:02X}, ver 0x{self.version:02X}, iface {self.interface}"


def decode_version(data: bytes) -> Version:
    """Parse a C3 32 XX YY version response."""
    if len(data) != VERSION_LEN:
        raise ProtocolError(f"Expected {VERSION_LEN} bytes, got {len(data)}: {data.hex(' ')}")
    if data[0] != 0xC3:
        raise ProtocolError(f"Unexpected head byte 0x{data[0]:02X} (want 0xC3)")
    yy = data[3]
    iface = _IFACE_NAMES.get((yy >> 4) & 0xF, "unknown")
    return Version(model=data[1], version=data[2], interface=iface, raw_iface_power=yy)
