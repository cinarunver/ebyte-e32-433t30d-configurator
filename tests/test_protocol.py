"""Protocol unit tests — no hardware required."""

import pytest

from e32config import protocol
from e32config.protocol import (
    AirRate, FEC, IODrive, Params, Parity, ProtocolError,
    TransmissionMode, TxPower, UartBaud, WakeupTime,
    channel_to_mhz, decode_params, decode_version, encode_params, mhz_to_channel,
)

# Manual default frame (E32-433T30D v1.9, section 7.1)
DEFAULT_FRAME = bytes.fromhex("C0 00 00 1A 17 40".replace(" ", ""))


def test_default_frame_round_trips():
    params = decode_params(DEFAULT_FRAME)
    assert encode_params(params, save=True) == DEFAULT_FRAME


def test_default_frame_field_values():
    p = decode_params(DEFAULT_FRAME)
    assert p.addr_high == 0x00 and p.addr_low == 0x00
    assert p.parity is Parity.N8N1
    assert p.uart_baud is UartBaud.B9600
    assert p.air_rate is AirRate.A2_4K
    assert p.channel == 0x17
    assert p.frequency_mhz == 433


def test_sped_0x1a_decodes_to_8n1_9600_2k4():
    parity, baud, air = protocol._decode_sped(0x1A)
    assert (parity, baud, air) == (Parity.N8N1, UartBaud.B9600, AirRate.A2_4K)


def test_option_0x40_bit_faithful():
    # 0x40 = 0100 0000 : transparent, push-pull, 250ms, FEC OFF, 30 dBm.
    mode, io, wake, fec, power = protocol._decode_option(0x40)
    assert mode is TransmissionMode.TRANSPARENT
    assert io is IODrive.PUSH_PULL
    assert wake is WakeupTime.T250
    assert fec is FEC.OFF
    assert power is TxPower.P30


def test_channel_frequency_bounds():
    assert channel_to_mhz(0x00) == 410
    assert channel_to_mhz(0x17) == 433
    assert channel_to_mhz(0x1F) == 441
    assert mhz_to_channel(433) == 0x17
    with pytest.raises(ProtocolError):
        mhz_to_channel(500)


def test_parity_0b11_normalises_to_8n1():
    # bits 11 in the parity field also mean 8N1 per the manual.
    parity, _, _ = protocol._decode_sped(0b11 << 6)
    assert parity is Parity.N8N1


def test_air_rate_high_codes_normalise_to_19k2():
    for code in (0b101, 0b110, 0b111):
        _, _, air = protocol._decode_sped(code)
        assert air is AirRate.A19_2K


def test_encode_temp_uses_c2_head():
    p = Params()
    assert encode_params(p, save=False)[0] == protocol.HEAD_TEMP
    assert encode_params(p, save=True)[0] == protocol.HEAD_SAVE


def test_full_field_round_trip():
    p = Params(
        addr_high=0xAB, addr_low=0xCD,
        parity=Parity.N8E1, uart_baud=UartBaud.B57600, air_rate=AirRate.A19_2K,
        channel=0x0A, transmission_mode=TransmissionMode.FIXED,
        io_drive=IODrive.OPEN_COLLECTOR, wakeup_time=WakeupTime.T2000,
        fec=FEC.ON, tx_power=TxPower.P21,
    )
    frame = encode_params(p, save=True)
    back = decode_params(frame)
    assert back == p


def test_decode_params_rejects_bad_length():
    with pytest.raises(ProtocolError):
        decode_params(b"\xC0\x00\x00")


def test_decode_params_rejects_bad_head():
    with pytest.raises(ProtocolError):
        decode_params(bytes.fromhex("FF00001A1740"))


def test_decode_version():
    v = decode_version(bytes([0xC3, 0x32, 0x0D, 0x10]))
    assert v.model == 0x32
    assert v.version == 0x0D
    assert v.interface == "TTL"


def test_decode_version_rejects_bad_frame():
    with pytest.raises(ProtocolError):
        decode_version(b"\xC3\x32\x0D")
    with pytest.raises(ProtocolError):
        decode_version(bytes([0xFF, 0x32, 0x0D, 0x10]))
