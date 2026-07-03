import pytest

from e32config.protocol import Params
from e32config.uimodel import (
    ENUM_FIELDS, address_calc, channel_calc, describe, enum_options,
    parse_address, parse_channel, parse_int,
)
from e32config.protocol import Parity


def test_parse_int_decimal_and_hex():
    assert parse_int("23") == 23
    assert parse_int("0x17") == 23
    assert parse_int(" 0X1F ") == 31


def test_parse_int_empty_raises():
    with pytest.raises(ValueError):
        parse_int("")


def test_parse_channel_bounds():
    assert parse_channel("0") == 0
    assert parse_channel("31") == 31
    assert parse_channel("0x1f") == 31
    with pytest.raises(ValueError):
        parse_channel("32")


def test_parse_address_bounds():
    assert parse_address("0") == 0
    assert parse_address("65535") == 65535
    assert parse_address("0xFFFF") == 65535
    with pytest.raises(ValueError):
        parse_address("65536")


def test_channel_calc_ok_and_invalid():
    text, ok = channel_calc("23")
    assert ok is True
    assert text == "frequency = 410 + 23 = 433 MHz  (0x17)"
    text, ok = channel_calc("99")
    assert ok is False
    assert text.startswith("invalid:")


def test_address_calc_ok_and_invalid():
    text, ok = address_calc("0")
    assert ok is True
    assert text == "0x0000 → ADDH=0x00  ADDL=0x00"
    text, ok = address_calc("nope")
    assert ok is False
    assert text.startswith("invalid:")


def test_enum_options_shape():
    opts = enum_options(Parity)
    assert ("8N1", 0) in opts
    assert all(isinstance(label, str) and isinstance(val, int) for label, val in opts)


def test_enum_fields_cover_params():
    attrs = {attr for _wid, _label, _enum, attr in ENUM_FIELDS}
    for attr in attrs:
        assert hasattr(Params(), attr)


def test_describe_default_params():
    s = describe(Params())
    assert "ch=0x17(433MHz)" in s
    assert "uart=9600/8N1" in s
    assert "pwr=30dBm" in s
