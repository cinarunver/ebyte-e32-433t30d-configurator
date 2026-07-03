# E32 Config TUI — Design Spec

**Date:** 2026-07-03
**Status:** Approved (pending written-spec review)

## Purpose

A cross-platform, terminal-based configuration tool for the **Ebyte E32-433T30D**
(SX1278, 433 MHz, 1W LoRa) wireless serial module. It reads and writes the module's
operating parameters over its UART configuration interface, presenting them in a
live, modern TUI instead of forcing the user to hand-craft hex command bytes.

Scope is **parameter configuration only** — not runtime data transmission
(no fixed/broadcast/monitor messaging).

## Hardware Context (critical)

The E32 enters configuration mode only when its **physical mode pins** are set to
**Mode 3: M0=1, M1=1** (both high). The configuration UART is fixed at **9600 baud, 8N1**
regardless of the module's stored baud setting. The software **cannot** control M0/M1
(they are hardware pins), so the tool must clearly instruct the user to set the module
to Mode 3 and wire it up before configuring:

```
USB-TTL adapter        E32-433T30D
  TXD  ───────────────►  RXD (pin 3)
  RXD  ◄───────────────  TXD (pin 4)
  GND  ───────────────   GND (pin 7)
  3.3~5V ─────────────   VCC (pin 6)
                         M0 (pin 1) ── HIGH
                         M1 (pin 2) ── HIGH   (Mode 3 = config)
```

After power-on / mode change the module drives **AUX low** during self-check; the tool
should tolerate an initial busy period (wait/retry on first command).

## Command Reference (from E32-433T30D manual v1.9)

All commands are issued in sleep/config mode (M0=1, M1=1), 9600 8N1, HEX.

| Command | Bytes sent | Response | Meaning |
|---------|-----------|----------|---------|
| Read params | `C1 C1 C1` | `C0 ADDH ADDL SPED CHAN OPTION` (6B) | Read current config |
| Write (save) | `C0 ADDH ADDL SPED CHAN OPTION` (6B) | echoes params | Save on power-down |
| Write (temp) | `C2 ADDH ADDL SPED CHAN OPTION` (6B) | echoes params | Not saved on power-down |
| Read version | `C3 C3 C3` | `C3 32 XX YY` (4B) | model/version/iface+power |
| Reset | `C4 C4 C4` | (module resets) | Factory/soft reset |

**Default params:** `C0 00 00 1A 17 40`.

### Bit-field decoding

**SPED byte:**
- bit 7-6 → UART parity: `00`/`11`=8N1, `01`=8O1, `10`=8E1
- bit 5-3 → UART baud: 000=1200, 001=2400, 010=4800, 011=9600, 100=19200,
  101=38400, 110=57600, 111=115200
- bit 2-0 → air data rate: 000=0.3k, 001=1.2k, 010=2.4k, 011=4.8k, 100=9.6k,
  101/110/111=19.2k

**CHAN byte:** bits 4-0 = channel; frequency = **410 MHz + CHAN·1 MHz** (00H–1FH → 410–441 MHz).
Default 0x17 = 433 MHz. Bits 7-5 reserved (write 0).

**OPTION byte:**
- bit 7 → transmission mode: 0=transparent, 1=fixed
- bit 6 → IO drive: 1=push-pull/pull-up (default), 0=open-collector
- bit 5-3 → wireless wake-up time: 000=250ms … 111=2000ms (250ms steps)
- bit 2 → FEC: 1=on (default), 0=off
- bit 1-0 → TX power: 00=30dBm, 01=27, 10=24, 11=21

**Version response `C3 32 XX YY`:** `32`=product model, `XX`=version,
`YY`=interface+max power (TTL=0x10, RS232=0x40, RS485=0x80 in the high nibble).

### Reference vector (must round-trip in tests)
`C0 00 00 1A 17 40` → ADDH=0x00, ADDL=0x00, SPED=0x1A (8N1 / 9600 / 2.4k),
CHAN=0x17 (433 MHz), OPTION=0x40. Decoding OPTION=0x40 (`0100 0000`) by the bit table:
transparent, push-pull IO, 250ms wake-up, **FEC bit=0 (off)**, TX power=30 dBm.

> **Source discrepancy:** the manual's prose calls FEC "on (default)" yet its own
> default byte `0x40` has the FEC bit clear. The tool is **bit-faithful** — decode/encode
> reflect the actual bit values, never the prose. The round-trip test asserts on the raw
> bytes, so this stays internally consistent regardless of the manual's wording.

## Architecture

Three isolated layers; the protocol layer has zero I/O and zero UI dependencies.

### 1. `protocol.py` — pure logic (no hardware needed to test)
- `@dataclass Params` with typed enum fields (parity, uart_baud, air_rate,
  channel, tx_power, fec, transmission_mode, io_drive, wakeup_time, addr_high, addr_low).
- `decode_params(data: bytes) -> Params` — parses a 6-byte `C0/C1` response.
- `encode_params(p: Params, save: bool) -> bytes` — builds `C0`(save)/`C2`(temp) frame.
- `decode_version(data: bytes) -> Version` — parses `C3 32 XX YY`.
- Enums mirror the manual tables exactly; helpers like `channel_to_mhz(chan)`.
- Frame builders for the fixed commands: `READ_PARAMS = b"\xC1\xC1\xC1"`,
  `READ_VERSION = b"\xC3\xC3\xC3"`, `RESET = b"\xC4\xC4\xC4"`.
- Raises `ProtocolError` on wrong length / wrong header.

### 2. `transport.py` — serial I/O
- `Transport` protocol/ABC: `send(cmd: bytes) -> None`, `read(n, timeout) -> bytes`,
  `close()`.
- `SerialTransport(port, baud=9600)` using `pyserial` (8N1). `command(cmd, expected_len)`
  helper: flush, write, read expected bytes with timeout, return raw.
- `list_ports() -> list[PortInfo]` via `serial.tools.list_ports` (cross-platform).
- Keeping `Transport` abstract lets protocol/app logic be unit-tested with a fake.

### 3. `app.py` — Textual TUI
- **Header:** port dropdown (auto-listed + manual entry), baud fixed 9600, Connect button,
  connection/status indicator, and a persistent "Set module to Mode 3 (M0=1,M1=1)" hint.
- **Read** → send `C1C1C1`, decode, populate an editable form.
- **Form fields** as Select/Input widgets: address (H/L hex), channel (with live MHz),
  air rate, UART baud, parity, TX power, FEC, wake-up time, transmission mode, IO drive.
- **Write (save / C0)** and **Write (temp / C2)** buttons → confirmation summary → send →
  read-back with `C1` to verify and report success/mismatch.
- **Version (C3)** and **Reset (C4)** buttons (Reset behind a confirm).
- **Log panel** (bottom): live TX/RX hex bytes + human-readable events + errors.

### Data flow
```
UI widgets ⇄ Params dataclass ⇄ protocol.encode/decode ⇄ Transport ⇄ serial port
```
The protocol layer never imports textual or pyserial.

## Error Handling
- Port open failure, read timeout, unexpected response length/header → surfaced in the
  log panel as a clear message; the app never crashes.
- First command after connect may time out due to AUX-busy self-check → one automatic retry.
- Write verification: after a write, re-read with `C1`; if bytes differ from what was sent,
  flag a mismatch warning.

## Testing
- `tests/test_protocol.py` (pytest):
  - Round-trip `C0 00 00 1A 17 40` decode→encode reproduces the bytes.
  - `SPED 0x1A` decodes to 8N1 / 9600 / 2.4k.
  - `CHAN 0x17` → 433 MHz; `channel_to_mhz` spot checks (0x00→410, 0x1F→441).
  - `OPTION` decode for each field; TX power / FEC / wakeup mappings.
  - Version parse of a `C3 32 XX YY` sample.
  - `ProtocolError` on short / wrong-header input.
- Transport logic exercised with a fake `Transport` (no real port required).

## Cross-Platform & Distribution
Pure Python; `pyserial` + `textual` support Linux, macOS, Windows, and BSD.
Port auto-listing covers `/dev/ttyUSB*`, `/dev/cu.*`, `COMx`, `/dev/cuaU*`.

Three documented install paths (in README):
1. **pipx/pip** — `pipx install git+https://github.com/<user>/e32config` (or PyPI later).
2. **From source** — clone → `python -m venv` → `pip install -e .` → `python -m e32config`.
3. **Standalone binary** — PyInstaller single-file per OS, built by a GitHub Actions
   matrix (Linux/macOS/Windows) and attached to Releases. BSD: source install
   (PyInstaller unsupported on BSD — stated explicitly).

## Project Layout
```
e32config/
├── src/e32config/
│   ├── __init__.py
│   ├── __main__.py        # entry: launches the Textual app
│   ├── protocol.py
│   ├── transport.py
│   └── app.py
├── tests/test_protocol.py
├── pyproject.toml         # deps (pyserial, textual), console_scripts entry point, metadata
├── README.md              # purpose, wiring diagram, 3 install paths per-OS, usage, param table, troubleshooting
├── LICENSE                # MIT
├── .gitignore
└── .github/workflows/build.yml   # PyInstaller matrix → Releases
```

## YAGNI (explicitly out of scope)
- Runtime data messaging (fixed/broadcast/monitor transmission).
- Setting M0/M1 in software (hardware pins).
- Support for other E32 variants beyond 433T30D (parameter map is shared for most,
  but only 433T30D is validated here).
- A simulator UI (protocol layer is testable without one; not shipping a fake device mode).

## License
MIT — maximally permissive, per user request ("herkese açık olsun").
