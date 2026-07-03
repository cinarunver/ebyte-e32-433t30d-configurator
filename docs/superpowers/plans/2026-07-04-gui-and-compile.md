# Windowed GUI + Dual-Binary Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a windowed CustomTkinter GUI (feature-parity with the existing Textual TUI) that reuses the same core, extract shared UI-agnostic helpers so nothing is duplicated, and compile both front-ends to single-file binaries locally and in CI.

**Architecture:** `protocol.py` and `transport.py` are untouched. A new `uimodel.py` holds UI-agnostic form helpers extracted verbatim from `app.py`; both the TUI (`app.py`, refactored) and the new GUI (`gui.py`) import from it. The GUI runs all serial I/O on short-lived background threads and marshals results to the UI thread through a `queue.Queue` drained by a periodic `after()` poll, so the window never freezes. A single `scripts/build.py` produces both binaries for local use and CI.

**Tech Stack:** Python ≥3.9, pyserial, textual (TUI), customtkinter (GUI), PyInstaller (compile), pytest.

## Global Constraints

- Python floor: **>=3.9**. Use `from __future__ import annotations` in every new module so `X | None`, `list[...]`, `dict[...]`, `tuple[...]` annotations are legal on 3.9.
- Do **not** modify `protocol.py` or `transport.py`.
- The refactor of `app.py` must be **behavior-preserving** — the TUI's observable output stays identical.
- Base dependencies include both `textual` and `customtkinter` so `pip install -e .` provides both front-ends.
- Commit messages: **never** add a `Co-Authored-By: Claude` trailer or any Claude authorship. Plain messages only. (User instruction.)
- License stays MIT; cross-platform (Win/macOS/Linux) is a hard requirement.

---

### Task 1: Extract shared UI helpers into `uimodel.py` and refactor the TUI

**Files:**
- Create: `src/e32config/uimodel.py`
- Test: `tests/test_uimodel.py`
- Modify: `src/e32config/app.py` (remove local copies; import from `uimodel`)

**Interfaces:**
- Consumes: from `e32config.protocol` — `channel_to_mhz`, `CHAN_MIN`, `CHAN_MAX`, `Params`, and the enum classes.
- Produces (relied on by Tasks 1 & 3):
  - `ENUM_FIELDS: list[tuple[str, str, type, str]]` — `(widget_id, label, enum_cls, params_attr)`
  - `enum_options(enum_cls) -> list[tuple[str, int]]`
  - `parse_int(text: str) -> int`
  - `parse_channel(text: str) -> int`
  - `parse_address(text: str) -> int`
  - `channel_calc(text: str) -> tuple[str, bool]`
  - `address_calc(text: str) -> tuple[str, bool]`
  - `describe(p: Params) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_uimodel.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_uimodel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'e32config.uimodel'`.

- [ ] **Step 3: Create `src/e32config/uimodel.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_uimodel.py -q`
Expected: PASS (all tests green).

- [ ] **Step 5: Refactor `app.py` to import from `uimodel`**

In `src/e32config/app.py`:

1. Replace the protocol/enum import block and add the uimodel import. Change the imports near the top so that after the existing `from . import __version__, protocol` line, the enum import is trimmed to only what the file still uses and the shared helpers come from `uimodel`:

```python
from . import __version__, protocol
from .protocol import Params, ProtocolError
from .transport import (
    PortInfo, SerialTransport, TransportError, list_serial_ports,
)
from .uimodel import (
    ENUM_FIELDS, address_calc, channel_calc, describe, enum_options,
    parse_address, parse_channel,
)
```

2. **Delete** these now-duplicated definitions from `app.py`: the module-level `_ENUM_FIELDS` list, `_enum_options`, `_parse_int`, `_parse_channel`, `_parse_address`, and the static method `_describe`.

3. Replace remaining references:
   - `_ENUM_FIELDS` → `ENUM_FIELDS` (in `compose`, `_load_params_into_form`, `_read_params_from_form`).
   - `_enum_options(enum_cls)` → `enum_options(enum_cls)`.
   - In `_read_params_from_form`: `_parse_channel(...)` → `parse_channel(...)`, `_parse_address(...)` → `parse_address(...)`.
   - `self._describe(params)` / `self._describe(p)` → `describe(params)` / `describe(p)`.

4. Rewrite the two calc methods to use the shared helpers:

```python
    def _update_channel_calc(self) -> None:
        label = self.query_one("#channel_calc", Label)
        text, ok = channel_calc(self.query_one("#channel", Input).value)
        label.update(text)
        label.set_classes("calc" if ok else "calc-err")

    def _update_addr_calc(self) -> None:
        label = self.query_one("#addr_calc", Label)
        text, ok = address_calc(self.query_one("#address", Input).value)
        label.update(text)
        label.set_classes("calc" if ok else "calc-err")
```

- [ ] **Step 6: Verify the TUI still imports and the whole suite passes**

Run: `.venv/bin/python -c "import e32config.app"`
Expected: no output, exit 0 (no NameError from a missed reference).

Run: `.venv/bin/pytest -q`
Expected: PASS — `test_protocol.py` and `test_uimodel.py` all green.

- [ ] **Step 7: Commit**

```bash
git add src/e32config/uimodel.py tests/test_uimodel.py src/e32config/app.py
git commit -m "refactor: extract shared UI helpers into uimodel; reuse in TUI"
```

---

### Task 2: Add the GUI dependency and entry point

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/e32config/__main__.py`

**Interfaces:**
- Produces: a `gui_main() -> int` console entry (guarded import, mirrors `main()`), and the `e32config-gui` script mapping. Task 3 supplies the `e32config.gui:run` it imports.

- [ ] **Step 1: Add `customtkinter` to dependencies**

In `pyproject.toml`, change the `dependencies` array to:

```toml
dependencies = [
    "pyserial>=3.5",
    "textual>=0.60",
    "customtkinter>=5.2",
]
```

- [ ] **Step 2: Add the GUI console script**

In `pyproject.toml`, change `[project.scripts]` to:

```toml
[project.scripts]
e32config = "e32config.__main__:main"
e32config-gui = "e32config.__main__:gui_main"
```

- [ ] **Step 3: Add the guarded `gui_main` entry to `__main__.py`**

In `src/e32config/__main__.py`, add this function after the existing `main()`:

```python
def gui_main() -> int:
    try:
        from .gui import run
    except ImportError as exc:  # pragma: no cover - dependency guard
        print(f"Missing dependency: {exc}\nInstall with: pip install e32config", file=sys.stderr)
        return 1
    run()
    return 0
```

- [ ] **Step 4: Reinstall and verify the dependency resolves**

Run: `.venv/bin/pip install -e . -q && .venv/bin/python -c "import customtkinter; print('ok')"`
Expected: prints `ok` (customtkinter installed and importable).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/e32config/__main__.py
git commit -m "build: add customtkinter dep and e32config-gui entry point"
```

---

### Task 3: Implement the CustomTkinter GUI

**Files:**
- Create: `src/e32config/gui.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: `uimodel` helpers (Task 1); `protocol` frames/decoders; `transport` (`SerialTransport`, `TransportError`, `list_serial_ports`).
- Produces: `run() -> None` (constructs the window and enters `mainloop()`); class `E32Gui`. Consumed by `__main__.gui_main` (Task 2) and `scripts/build.py` (Task 4).

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_gui_smoke.py`:

```python
def test_gui_module_exposes_entry_points():
    import e32config.gui as gui

    assert callable(gui.run)
    assert hasattr(gui, "E32Gui")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_smoke.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'e32config.gui'`.

- [ ] **Step 3: Create `src/e32config/gui.py`**

```python
"""CustomTkinter windowed GUI for reading/writing E32-433T30D parameters.

Serial I/O runs on short-lived background threads; results are marshalled back
to the Tk main thread through a queue drained by a periodic `after()` poll, so
the window never freezes (a first post-connect command can block ~2s while the
module drives AUX low during self-check). Tk widgets are only ever touched on
the main thread.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

import customtkinter as ctk

from . import __version__, protocol
from .protocol import Params, ProtocolError
from .transport import (
    PortInfo, SerialTransport, TransportError, list_serial_ports,
)
from .uimodel import (
    ENUM_FIELDS, address_calc, channel_calc, describe, enum_options,
    parse_address, parse_channel,
)

HINT = "Set the module to Mode 3 (M0=1, M1=1) and wire RXD/TXD/GND before connecting."
OK_COLOR = "#2a8f2a"
ERR_COLOR = "#c0392b"


class E32Gui(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"e32config — E32-433T30D LoRa configurator v{__version__}")
        self.geometry("840x740")

        self._transport: SerialTransport | None = None
        self._ports: list[PortInfo] = []
        self._port_map: dict[str, str] = {}
        self._confirm_reset = False
        self._q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._enum_menus: dict[str, tuple[ctk.CTkOptionMenu, dict[str, int], dict[int, str]]] = {}
        self._action_buttons: list[ctk.CTkButton] = []

        self._build_topbar()
        self._build_form()
        self._build_actions()
        self._build_log()

        self._refresh_ports()
        self._log("Ready. Select a port and press Connect.")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain)

    # -- layout --------------------------------------------------------------
    def _build_topbar(self) -> None:
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self._port_menu = ctk.CTkOptionMenu(bar, values=["<no ports found>"], width=420)
        self._port_menu.pack(side="left", padx=(8, 8), pady=8)
        self._connect_btn = ctk.CTkButton(bar, text="Connect", width=100, command=self._on_connect)
        self._connect_btn.pack(side="left", padx=6)
        self._refresh_btn = ctk.CTkButton(bar, text="Refresh", width=90, command=self._refresh_ports)
        self._refresh_btn.pack(side="left", padx=6)

        self._status = ctk.CTkLabel(self, text="Not connected.", anchor="w")
        self._status.pack(fill="x", padx=14)
        ctk.CTkLabel(self, text=HINT, anchor="w", text_color="#d89a1e").pack(fill="x", padx=14, pady=(0, 4))

    def _build_form(self) -> None:
        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=10, pady=4)
        form.grid_columnconfigure(0, weight=1)
        form.grid_columnconfigure(1, weight=1)

        for idx, (wid, label, enum_cls, _attr) in enumerate(ENUM_FIELDS):
            row, col = divmod(idx, 2)
            cell = ctk.CTkFrame(form, fg_color="transparent")
            cell.grid(row=row, column=col, sticky="ew", padx=6, pady=4)
            cell.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(cell, text=label, anchor="w").grid(row=0, column=0, sticky="w")
            options = enum_options(enum_cls)
            fwd = {lbl: val for lbl, val in options}
            rev = {val: lbl for lbl, val in options}
            menu = ctk.CTkOptionMenu(cell, values=[lbl for lbl, _ in options])
            menu.grid(row=1, column=0, sticky="ew")
            self._enum_menus[wid] = (menu, fwd, rev)

        base_row = (len(ENUM_FIELDS) + 1) // 2

        ch_cell = ctk.CTkFrame(form, fg_color="transparent")
        ch_cell.grid(row=base_row, column=0, sticky="ew", padx=6, pady=4)
        ch_cell.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ch_cell, text="Channel (0–31, or 0x..)", anchor="w").grid(row=0, column=0, sticky="w")
        self._channel_var = ctk.StringVar(value="23")
        ctk.CTkEntry(ch_cell, textvariable=self._channel_var).grid(row=1, column=0, sticky="ew")
        self._channel_calc = ctk.CTkLabel(ch_cell, text="", anchor="w")
        self._channel_calc.grid(row=2, column=0, sticky="w")
        self._channel_var.trace_add("write", lambda *_: self._update_channel_calc())

        addr_cell = ctk.CTkFrame(form, fg_color="transparent")
        addr_cell.grid(row=base_row, column=1, sticky="ew", padx=6, pady=4)
        addr_cell.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(addr_cell, text="Address (0–65535, or 0x..)", anchor="w").grid(row=0, column=0, sticky="w")
        self._address_var = ctk.StringVar(value="0")
        ctk.CTkEntry(addr_cell, textvariable=self._address_var).grid(row=1, column=0, sticky="ew")
        self._addr_calc = ctk.CTkLabel(addr_cell, text="", anchor="w")
        self._addr_calc.grid(row=2, column=0, sticky="w")
        self._address_var.trace_add("write", lambda *_: self._update_addr_calc())

        self._update_channel_calc()
        self._update_addr_calc()

    def _build_actions(self) -> None:
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=10, pady=4)
        specs = [
            ("Read (C1)", self._on_read),
            ("Write save (C0)", self._on_write_save),
            ("Write temp (C2)", self._on_write_temp),
            ("Version (C3)", self._on_version),
            ("Reset (C4)", self._on_reset),
        ]
        for text, cmd in specs:
            btn = ctk.CTkButton(bar, text=text, command=cmd)
            btn.pack(side="left", padx=6, pady=8)
            self._action_buttons.append(btn)

    def _build_log(self) -> None:
        self._logbox = ctk.CTkTextbox(self, wrap="none")
        self._logbox.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._logbox.configure(state="disabled")

    # -- helpers -------------------------------------------------------------
    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._logbox.configure(state="normal")
        self._logbox.insert("end", f"{ts}  {msg}\n")
        self._logbox.see("end")
        self._logbox.configure(state="disabled")

    def _update_channel_calc(self) -> None:
        text, ok = channel_calc(self._channel_var.get())
        self._channel_calc.configure(text=text, text_color=(OK_COLOR if ok else ERR_COLOR))

    def _update_addr_calc(self) -> None:
        text, ok = address_calc(self._address_var.get())
        self._addr_calc.configure(text=text, text_color=(OK_COLOR if ok else ERR_COLOR))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for btn in self._action_buttons:
            btn.configure(state=state)
        self._connect_btn.configure(state=state)

    def _require_transport(self) -> SerialTransport | None:
        if self._transport is None:
            self._log("Not connected. Press Connect first.")
            return None
        return self._transport

    def _refresh_ports(self) -> None:
        self._ports = list_serial_ports()
        self._port_map = {p.label: p.device for p in self._ports}
        labels = list(self._port_map) or ["<no ports found>"]
        self._port_menu.configure(values=labels)
        self._port_menu.set(labels[0])
        self._log(f"Found {len(self._ports)} serial port(s).")

    # -- worker plumbing -----------------------------------------------------
    def _post(self, kind: str, payload: object = None) -> None:
        """Called from worker threads; hands a message to the UI thread."""
        self._q.put((kind, payload))

    def _start(self, target: Callable[[], None]) -> None:
        self._set_busy(True)
        threading.Thread(target=target, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self._status.configure(text=str(payload))
                elif kind == "params":
                    self._load_params_into_form(payload)  # type: ignore[arg-type]
                elif kind == "transport":
                    self._transport = payload  # type: ignore[assignment]
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    # -- form <-> Params -----------------------------------------------------
    def _load_params_into_form(self, p: Params) -> None:
        for wid, _label, _enum_cls, attr in ENUM_FIELDS:
            menu, _fwd, rev = self._enum_menus[wid]
            menu.set(rev[int(getattr(p, attr))])
        self._channel_var.set(str(p.channel))
        self._address_var.set(str(p.address))

    def _read_params_from_form(self) -> Params:
        vals: dict = {}
        for wid, _label, enum_cls, attr in ENUM_FIELDS:
            menu, fwd, _rev = self._enum_menus[wid]
            vals[attr] = enum_cls(fwd[menu.get()])
        try:
            vals["channel"] = parse_channel(self._channel_var.get())
        except ValueError as exc:
            raise ProtocolError(f"Channel: {exc}") from exc
        try:
            addr = parse_address(self._address_var.get())
        except ValueError as exc:
            raise ProtocolError(f"Address: {exc}") from exc
        vals["addr_high"] = (addr >> 8) & 0xFF
        vals["addr_low"] = addr & 0xFF
        return Params(**vals)

    # -- actions (UI thread reads widgets, then hands I/O to a worker) --------
    def _on_connect(self) -> None:
        label = self._port_menu.get()
        device = self._port_map.get(label)
        if not device:
            self._log("No port selected.")
            return
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._start(lambda: self._worker_connect(device))

    def _worker_connect(self, device: str) -> None:
        try:
            t = SerialTransport(device, baud=9600)
        except TransportError as exc:
            self._post("status", "Connection failed")
            self._post("log", str(exc))
            self._post("done")
            return
        self._post("transport", t)
        self._post("status", f"Connected to {device} @ 9600 8N1")
        self._post("log", f"Opened {device}. Press Read to fetch current params.")
        self._post("done")

    def _on_read(self) -> None:
        t = self._require_transport()
        if not t:
            return
        self._start(lambda: self._worker_read(t))

    def _worker_read(self, t: SerialTransport) -> None:
        try:
            self._post("log", f"TX {protocol.READ_PARAMS.hex(' ')}")
            data = t.command(protocol.READ_PARAMS, protocol.PARAM_LEN, retries=1)
            self._post("log", f"RX {data.hex(' ')}")
            params = protocol.decode_params(data)
            self._post("params", params)
            self._post("log", describe(params))
        except (TransportError, ProtocolError) as exc:
            self._post("log", str(exc))
        finally:
            self._post("done")

    def _on_write_save(self) -> None:
        self._begin_write(save=True)

    def _on_write_temp(self) -> None:
        self._begin_write(save=False)

    def _begin_write(self, save: bool) -> None:
        t = self._require_transport()
        if not t:
            return
        try:
            params = self._read_params_from_form()
        except (ValueError, ProtocolError) as exc:
            self._log(f"Invalid form values: {exc}")
            return
        frame = protocol.encode_params(params, save=save)
        kind = "C0 (persist)" if save else "C2 (temp)"
        self._log(f"Writing {kind}  {describe(params)}")
        self._start(lambda: self._worker_write(t, frame))

    def _worker_write(self, t: SerialTransport, frame: bytes) -> None:
        try:
            self._post("log", f"TX {frame.hex(' ')}")
            echo = t.command(frame, protocol.PARAM_LEN, retries=1)
            self._post("log", f"RX {echo.hex(' ')}")
        except (TransportError, ProtocolError) as exc:
            self._post("log", str(exc))
            self._post("done")
            return
        try:
            readback = t.command(protocol.READ_PARAMS, protocol.PARAM_LEN, retries=1)
            expected = bytes([protocol.HEAD_READBACK]) + frame[1:]
            if readback == expected:
                self._post("log", "Verified: module now matches the written config.")
            else:
                self._post("log", f"Mismatch after write. readback={readback.hex(' ')} expected={expected.hex(' ')}")
        except (TransportError, ProtocolError) as exc:
            self._post("log", f"Could not verify: {exc}")
        finally:
            self._post("done")

    def _on_version(self) -> None:
        t = self._require_transport()
        if not t:
            return
        self._start(lambda: self._worker_version(t))

    def _worker_version(self, t: SerialTransport) -> None:
        try:
            self._post("log", f"TX {protocol.READ_VERSION.hex(' ')}")
            data = t.command(protocol.READ_VERSION, protocol.VERSION_LEN, retries=1)
            self._post("log", f"RX {data.hex(' ')}")
            ver = protocol.decode_version(data)
            self._post("log", ver.label)
        except (TransportError, ProtocolError) as exc:
            self._post("log", str(exc))
        finally:
            self._post("done")

    def _on_reset(self) -> None:
        t = self._require_transport()
        if not t:
            return
        if not self._confirm_reset:
            self._confirm_reset = True
            self._log("Press Reset again to confirm module reset.")
            return
        self._confirm_reset = False
        self._start(lambda: self._worker_reset(t))

    def _worker_reset(self, t: SerialTransport) -> None:
        try:
            self._post("log", f"TX {protocol.RESET.hex(' ')}")
            t.send(protocol.RESET)
            self._post("log", "Reset command sent. The module reboots and runs self-check.")
        except TransportError as exc:
            self._post("log", str(exc))
        finally:
            self._post("done")

    def _on_close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self.destroy()


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    E32Gui().mainloop()


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run the smoke test**

Run: `.venv/bin/pytest tests/test_gui_smoke.py -q`
Expected: PASS (module imports; `run` callable; `E32Gui` present). Importing `customtkinter` does not require a display, so this works headless.

- [ ] **Step 5: Manually confirm the window launches (local, has a display)**

Run: `.venv/bin/python -m e32config.gui` (or `.venv/bin/e32config-gui` after Task 2's reinstall).
Expected: a window titled "e32config — …" opens with the port bar, parameter form (8 dropdowns + Channel/Address with live calc), 5 action buttons, and a log box. Typing in Channel updates the green "frequency = 410 + …" line live; typing an out-of-range value turns it red. Close the window to exit cleanly. (Skip if running headless; the smoke test covers CI.)

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — protocol, uimodel, and gui-smoke tests all green.

- [ ] **Step 7: Commit**

```bash
git add src/e32config/gui.py tests/test_gui_smoke.py
git commit -m "feat: add windowed CustomTkinter GUI with threaded serial I/O"
```

---

### Task 4: Local dual-binary build script

**Files:**
- Create: `scripts/build.py`

**Interfaces:**
- Consumes: PyInstaller (from the `[build]` extra), `src/e32config/__main__.py` (CLI/TUI entry) and `src/e32config/gui.py` (GUI entry).
- Produces: `dist/e32config[.exe]` and `dist/e32config-gui[.exe]`. `python scripts/build.py --only {cli,gui}` builds one.

- [ ] **Step 1: Create `scripts/build.py`**

```python
#!/usr/bin/env python3
"""Build standalone single-file binaries for both e32config front-ends.

Single source of truth for local builds and CI (.github/workflows/build.yml).

    python scripts/build.py            # build both (CLI + GUI)
    python scripts/build.py --only cli
    python scripts/build.py --only gui

Outputs land in ./dist. Requires the build extra: pip install -e .[build]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "e32config"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def build_cli() -> None:
    """Console binary running the Textual TUI."""
    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--name", "e32config",
        str(SRC / "__main__.py"),
    ])


def build_gui() -> None:
    """Windowed binary running the CustomTkinter GUI.

    --windowed suppresses a stray console; --collect-all customtkinter bundles
    its theme/asset JSON so the compiled app starts (without it the GUI fails).
    """
    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "e32config-gui",
        "--collect-all", "customtkinter",
        str(SRC / "gui.py"),
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["cli", "gui"], help="build just one front-end")
    args = ap.parse_args()
    if args.only in (None, "cli"):
        build_cli()
    if args.only in (None, "gui"):
        build_gui()
    print("Binaries written to", ROOT / "dist", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Install the build extra**

Run: `.venv/bin/pip install -e .[build] -q && .venv/bin/python -c "import PyInstaller; print('pyinstaller ok')"`
Expected: prints `pyinstaller ok`.

- [ ] **Step 3: Build both binaries locally and verify they exist**

Run: `.venv/bin/python scripts/build.py`
Expected: PyInstaller runs twice; ends with "Binaries written to …/dist".

Run: `ls dist` (Windows: `dir dist`)
Expected: `e32config` and `e32config-gui` present (with `.exe` on Windows).

- [ ] **Step 4: Smoke-check the compiled CLI binary**

Run (unix): `./dist/e32config --help 2>&1 | head -1 || echo "launched"`
Expected: the binary runs (it launches the TUI; `launched` or a Textual screen is fine — the point is it does not crash on missing bundled modules). Press `q`/Ctrl-C to exit if the TUI opens.

- [ ] **Step 5: Commit**

```bash
git add scripts/build.py
git commit -m "build: add cross-platform script to compile both binaries"
```

---

### Task 5: Update CI to build both binaries on all three OSes

**Files:**
- Modify: `.github/workflows/build.yml`

**Interfaces:**
- Consumes: `scripts/build.py` (Task 4).
- Produces: per-OS artifacts each containing both binaries; attached to Releases on `v*` tags.

- [ ] **Step 1: Replace the `binary` job**

In `.github/workflows/build.yml`, replace the entire `binary:` job (keep `test:` and `release:` unchanged) with:

```yaml
  binary:
    name: Binaries (${{ matrix.os }})
    needs: test
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            suffix: linux-x86_64
            ext: ""
          - os: macos-latest
            suffix: macos
            ext: ""
          - os: windows-latest
            suffix: windows
            ext: ".exe"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install + PyInstaller
        run: |
          python -m pip install --upgrade pip
          pip install -e .[build]
      - name: Build both binaries
        run: python scripts/build.py
      - name: Rename artifacts (unix)
        if: runner.os != 'Windows'
        run: |
          mv dist/e32config dist/e32config-${{ matrix.suffix }}
          mv dist/e32config-gui dist/e32config-gui-${{ matrix.suffix }}
      - name: Rename artifacts (windows)
        if: runner.os == 'Windows'
        run: |
          Rename-Item dist/e32config.exe e32config-${{ matrix.suffix }}.exe
          Rename-Item dist/e32config-gui.exe e32config-gui-${{ matrix.suffix }}.exe
      - uses: actions/upload-artifact@v4
        with:
          name: e32config-${{ matrix.suffix }}
          path: |
            dist/e32config-${{ matrix.suffix }}${{ matrix.ext }}
            dist/e32config-gui-${{ matrix.suffix }}${{ matrix.ext }}
```

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build.yml')); print('yaml ok')"`
Expected: prints `yaml ok`. (If PyYAML isn't installed: `.venv/bin/pip install pyyaml -q` first.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/build.yml
git commit -m "ci: build and upload both binaries for all three OSes"
```

---

### Task 6: Document the GUI and both binaries in the README

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Read the current README to find the usage/install sections**

Run: `.venv/bin/python -c "print(open('README.md').read())"`
Expected: prints the README so you can see the existing "Usage" / "Install" / binary sections to slot the new content beside.

- [ ] **Step 2: Add a "Two front-ends" usage subsection**

Add this near the existing usage/run instructions (adapt surrounding headers to match the README's style):

```markdown
## Two front-ends

`e32config` ships two interchangeable interfaces over the same core — pick whichever suits you:

| Interface | Launch (installed) | Launch (from source) | Best for |
|-----------|--------------------|----------------------|----------|
| **Terminal (TUI)** | `e32config` | `python -m e32config` | terminals, SSH, no display |
| **Windowed (GUI)** | `e32config-gui` | `python -m e32config.gui` | desktop, mouse-driven use |

Both do the same thing: pick a serial port, Connect, then Read / Write (save C0 / temp C2) / Version / Reset. Remember the module must be in **Mode 3 (M0=1, M1=1)** and wired for 9600 8N1 first.
```

- [ ] **Step 3: Add a "Build standalone binaries" subsection**

Add this to the distribution/build section:

```markdown
## Build standalone binaries

Both front-ends compile to single-file executables with PyInstaller:

```bash
pip install -e .[build]
python scripts/build.py            # builds both -> ./dist
python scripts/build.py --only gui # or just one
```

This produces `dist/e32config` (terminal) and `dist/e32config-gui` (windowed), with `.exe` on Windows. CI (`.github/workflows/build.yml`) builds both for Linux, macOS, and Windows on every push and attaches them to GitHub Releases on `v*` tags. BSD: install from source (PyInstaller is unsupported there).
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the GUI front-end and dual-binary builds"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** uimodel extraction (Task 1) ✓; windowed GUI with parity + threading (Task 3) ✓; entry points + customtkinter dep (Task 2) ✓; local build script (Task 4) ✓; CI both-binaries (Task 5) ✓; README (Task 6) ✓; tests for uimodel + gui smoke (Tasks 1, 3) ✓; protocol/transport untouched ✓.
- **Threading invariant:** worker threads only ever call `self._post(...)`; every widget mutation happens in `_drain`, `_log`, the `_update_*_calc`, `_load_params_into_form`, or `_read_params_from_form` — all invoked on the Tk main thread. Do not add widget access inside a `_worker_*` method.
- **3.9 safety:** every new module starts with `from __future__ import annotations`; no runtime use of `X | Y` unions.
- **Commit hygiene:** no `Co-Authored-By` trailers anywhere.
```

