# e32config

A cross-platform terminal UI for configuring the **Ebyte E32-433T30D** (SX1278,
433 MHz, 1 W LoRa) wireless serial module. Read and write every operating
parameter — address, channel/frequency, air data rate, UART baud, parity, TX
power, FEC, wake-up time, transmission mode, IO drive — over the module's UART
config interface, without hand-crafting hex command bytes.

Runs on **Linux, macOS, Windows, and BSD** (pure Python: `pyserial` + `textual`).

```
┌ e32config — E32-433T30D LoRa configurator ─────────────────────────┐
│ Port  [ /dev/ttyUSB0 — USB-Serial CH340 ▾ ]  (Connect) (Refresh)   │
│ Set the module to Mode 3 (M0=1, M1=1) and wire RXD/TXD/GND.        │
│ Connected to /dev/ttyUSB0 @ 9600 8N1                               │
│ ┌ Parity ─┐ ┌ UART baud ┐ ┌ Air rate ┐ ┌ TX power ┐  ...          │
│ │ 8N1   ▾ │ │ 9600    ▾ │ │ 2.4k   ▾ │ │ 30dBm  ▾ │              │
│ ┌ Channel (0–31) ┐          ┌ Address (0–65535) ┐                │
│ │ 23             │          │ 22                │                │
│ frequency = 410 + 23 = 433 MHz   0x0016 → ADDH=0x00 ADDL=0x16    │
│ (Read C1) (Write save C0) (Write temp C2) (Version C3) (Reset C4) │
│ ┌ log ───────────────────────────────────────────────────────────┐│
│ │ 12:00:01 TX c1 c1 c1                                            ││
│ │ 12:00:01 RX c0 00 00 1a 17 40                                  ││
│ │ 12:00:01 addr=0x0000 ch=0x17(433MHz) air=2.4k uart=9600/8N1... ││
│ └────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────┘
```

---

## Hardware setup (read this first)

The E32 only accepts configuration commands when its **physical mode pins** are
set to **Mode 3: M0 = 1, M1 = 1** (both high). The config UART is fixed at
**9600 baud, 8N1**, regardless of the baud rate stored in the module.

Wire a USB-to-TTL (3.3 V logic recommended) adapter to the module:

```
USB-TTL adapter          E32-433T30D
  TXD  ───────────────►   RXD (pin 3)
  RXD  ◄───────────────   TXD (pin 4)
  GND  ────────────────   GND (pin 7)
  3.3–5 V ─────────────   VCC (pin 6)
                          M0  (pin 1) ── HIGH  ┐
                          M1  (pin 2) ── HIGH  ┘ Mode 3 = configuration
```

> ⚠️ 5 V TTL on RXD risks damaging the module — prefer a 3.3 V adapter, or add a
> series resistor. See the module manual, sections 3–4.

After power-on (or any mode change) the module runs a brief self-check with AUX
held low; the tool auto-retries the first command to ride through it.

---

## Install

### Option 1 — pipx / pip (recommended)

Requires Python 3.9+.

```bash
# from GitHub
pipx install git+https://github.com/USER/e32config

# or with plain pip in a virtualenv
pip install git+https://github.com/USER/e32config
```

Then run:

```bash
e32config
```

### Option 2 — from source (for development)

```bash
git clone https://github.com/USER/e32config
cd e32config

python -m venv .venv
# Linux / macOS / BSD:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e .[dev]
python -m e32config      # or: e32config
```

### Option 3 — standalone binary (no Python needed)

Prebuilt single-file executables for **Linux, macOS, and Windows** are attached
to each [GitHub Release](https://github.com/USER/e32config/releases). Download
the one for your OS, mark it executable, and run:

```bash
# Linux / macOS
chmod +x e32config-linux-x86_64
./e32config-linux-x86_64
```

```powershell
# Windows
.\e32config-windows.exe
```

Build one yourself:

```bash
pip install -e .[build]
pyinstaller --onefile --name e32config src/e32config/__main__.py
# result: dist/e32config
```

> **BSD note:** PyInstaller does not officially support the BSDs. On FreeBSD/
> OpenBSD/NetBSD install from source (Option 1 or 2) — `pyserial` and `textual`
> both work there. Serial ports appear as `/dev/cuaU0`, etc.

---

## Usage

1. Set the module to **Mode 3** (M0=1, M1=1) and connect it via USB-TTL.
2. Launch `e32config`.
3. Pick your serial port from the dropdown (**Refresh** to rescan) and press
   **Connect**. Ports are auto-detected on every platform:
   - Linux: `/dev/ttyUSB*`, `/dev/ttyACM*`
   - macOS: `/dev/cu.usbserial-*`
   - Windows: `COM3`, `COM4`, …
   - BSD: `/dev/cuaU*`
4. **Read (C1)** — fetch and display the current configuration.
5. Edit fields: dropdowns for the enum settings; **type the channel** (0–31, or
   `0x..`) — a live line shows the resulting frequency
   (`frequency = 410 + 23 = 433 MHz`) — and **type the address as a single number**
   (0–65535 decimal, or `0x..`); the tool splits it into the module's ADDH/ADDL
   bytes for you (`22` → `ADDH=0x00 ADDL=0x16`).
6. **Write save (C0)** persists across power-down; **Write temp (C2)** is lost on
   reboot. After a write the tool reads back and verifies the module matches.
7. **Version (C3)** shows model / firmware version / interface. **Reset (C4)**
   reboots the module (press twice to confirm).

Keyboard shortcuts: `r` read · `s` write-save · `t` write-temp · `v` version ·
`q` quit.

---

## Parameters

| Field | Values | Notes |
|-------|--------|-------|
| Address | `0`–`65535` (or `0x0000`–`0xFFFF`) | 16-bit; auto-split into ADDH/ADDL |
| Channel | `0`–`31` (or `0x00`–`0x1F`) | frequency = 410 MHz + channel; `23` = 433 MHz |
| Air data rate | 0.3k / 1.2k / 2.4k / 4.8k / 9.6k / 19.2k | lower = longer range; must match peer |
| UART baud | 1200 … 115200 | UART only; does not affect the radio |
| Parity | 8N1 / 8O1 / 8E1 | UART only |
| TX power | 30 / 27 / 24 / 21 dBm | 30 dBm = 1 W |
| FEC | on / off | must match peer |
| Wake-up time | 250 … 2000 ms | preamble for power-saving Mode 2 receivers |
| Transmission | transparent / fixed | fixed uses first 3 bytes as addr+channel |
| IO drive | push-pull / open-collector | pin drive behaviour |

Command reference (issued in Mode 3, 9600 8N1):

| Action | Bytes | Response |
|--------|-------|----------|
| Read params | `C1 C1 C1` | `C0 ADDH ADDL SPED CHAN OPTION` |
| Write (save) | `C0 …5 bytes` | echoes frame |
| Write (temp) | `C2 …5 bytes` | echoes frame |
| Read version | `C3 C3 C3` | `C3 32 XX YY` |
| Reset | `C4 C4 C4` | module reboots |

Module default: `C0 00 00 1A 17 40`.

---

## Troubleshooting

- **No ports listed** — check the USB-TTL adapter and its driver (CH340/CP210x/
  FTDI). Press **Refresh**. On Linux add your user to the `dialout` group
  (`sudo usermod -aG dialout $USER`, then re-login).
- **Timeout / no response** — the module is probably not in Mode 3. Confirm
  M0=1 and M1=1, and that TX↔RX are crossed (adapter TXD → module RXD).
- **Garbled bytes** — wrong baud. The config UART is always 9600 8N1; this tool
  fixes it, so suspect wiring/logic-level issues instead.
- **Mismatch after write** — re-check FEC/air-rate constraints; some field
  combinations are normalised by the module.
- **Permission denied on the port** — Linux `dialout` group (above); macOS may
  prompt for driver approval in System Settings.

---

## Development

```bash
pip install -e .[dev]
pytest -q          # protocol tests, no hardware needed
```

The code is split into three isolated layers:

- `protocol.py` — pure encode/decode and bit-field logic (fully unit-tested).
- `transport.py` — `pyserial` I/O and cross-platform port enumeration.
- `app.py` — the Textual TUI.

## License

MIT — do whatever you want with it.
# ebyte-e32-433t30d-configurator
