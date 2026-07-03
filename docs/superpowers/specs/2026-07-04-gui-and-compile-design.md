# E32 Config — GUI Version + Compilation Design Spec

**Date:** 2026-07-04
**Status:** Approved (pending written-spec review)
**Builds on:** [2026-07-03-e32config-design.md](2026-07-03-e32config-design.md)

## Purpose

The project currently ships a single interactive front-end: a Textual **TUI**
(`app.py`) that runs in the terminal. This work adds a second front-end — a
**windowed desktop GUI** (CustomTkinter) — while keeping the existing TUI intact.
Both front-ends reuse the same UI-agnostic core (`protocol.py`, `transport.py`).
Both are then compiled to standalone, single-file binaries for Windows, macOS,
and Linux, buildable both locally and in CI.

The two "versions" the user asked for are:
1. **Terminal version** — the existing Textual TUI (unchanged).
2. **Normal app** — a new windowed CustomTkinter GUI.

A separate flag-driven scriptable CLI (e.g. `e32config write --channel 23`) is
**out of scope** for this work (the core is ready if it is wanted later).

## Goals & Non-Goals

**Goals**
- Add a windowed GUI with feature parity to the TUI (read/write/version/reset,
  full parameter form, live channel/address calc, TX/RX log).
- Do not freeze the GUI window during serial I/O (background worker thread).
- Keep the existing TUI and its `e32config` entry point working unchanged.
- Extract UI-agnostic helpers currently in `app.py` into a shared module so the
  GUI does not duplicate them.
- Compile both front-ends to single-file binaries, locally and in CI, from one
  source of truth.

**Non-Goals (YAGNI)**
- A separate scriptable/flag-based CLI.
- Controlling M0/M1 in software (hardware pins).
- Support for E32 variants beyond 433T30D.
- Runtime data messaging (already out of scope in the base design).

## Architecture

The existing three-layer split is preserved and one shared UI helper module is
added. `protocol.py` and `transport.py` are **not modified**.

```
protocol.py   (pure logic — unchanged)
transport.py  (serial I/O — unchanged)
uimodel.py    (NEW — UI-agnostic form helpers, shared by both front-ends)
   ├── app.py   (TUI — Textual; refactored to import from uimodel)
   └── gui.py   (NEW — windowed GUI; CustomTkinter)
```

Data flow (both front-ends, identical):
```
widgets ⇄ uimodel helpers ⇄ Params ⇄ protocol.encode/decode ⇄ transport ⇄ serial
```

### 1. `uimodel.py` (NEW) — shared, UI-agnostic form logic

Extracted verbatim (behavior-preserving) from the current `app.py`. No Textual,
no CustomTkinter, no pyserial imports — pure functions/data over `protocol`.

- `ENUM_FIELDS: list[tuple[str, str, type, str]]` — `(widget_id, label, enum_cls, Params_attr)`.
- `enum_options(enum_cls) -> list[tuple[str, int]]`.
- `parse_int(text) -> int` — decimal or `0x` hex.
- `parse_channel(text) -> int` — validates 0..31 (`CHAN_MIN..CHAN_MAX`).
- `parse_address(text) -> int` — validates 0..65535.
- `channel_calc(text) -> tuple[str, bool]` — display string + `ok` flag, e.g.
  `("frequency = 410 + 23 = 433 MHz  (0x17)", True)` or `("invalid: 0..31 only", False)`.
- `address_calc(text) -> tuple[str, bool]` — e.g. `("0x0000 → ADDH=0x00  ADDL=0x00", True)`.
- `describe(p: Params) -> str` — the one-line human summary used in the log.

`app.py` is refactored to import these instead of defining its own copies; its
observable behavior is unchanged.

### 2. `gui.py` (NEW) — windowed GUI (CustomTkinter)

A `customtkinter.CTk` window with feature parity to the TUI:

- **Top bar:** port dropdown (`CTkOptionMenu`, populated from `list_serial_ports()`),
  **Connect** and **Refresh** buttons, and a connection-status label.
- **Hint label:** "Set the module to Mode 3 (M0=1, M1=1) and wire RXD/TXD/GND before connecting."
- **Parameter form:** 8 enum dropdowns (`CTkOptionMenu`, one per `ENUM_FIELDS` entry)
  plus Channel and Address entries (`CTkEntry`) with a live calc label under each,
  driven by `channel_calc` / `address_calc` (green when ok, red when invalid).
- **Action buttons:** Read (C1), Write save (C0), Write temp (C2), Version (C3),
  Reset (C4, behind a two-press confirm exactly like the TUI).
- **Log panel:** a scrollable read-only text box showing timestamped TX/RX hex and
  human-readable events/errors (same content the TUI's `RichLog` shows).

Form ⇄ `Params` mapping mirrors the TUI's `_load_params_into_form` /
`_read_params_from_form`, using `ENUM_FIELDS` and the shared parse helpers.

### 3. Threading model (the key GUI correctness point)

Tkinter/CustomTkinter is single-threaded; a blocking serial call (1 s timeout,
plus one retry → up to ~2 s, worse right after connect while the module drives
AUX low during self-check) would freeze the window. Therefore:

- Each device operation (connect, read, write, version, reset) runs on a
  **short-lived background `threading.Thread`**.
- Results/errors are pushed onto a `queue.Queue`; the UI thread drains it via a
  periodic `self.after(50, self._drain)` poll and updates widgets/log on the UI
  thread only. Tkinter widgets are never touched from the worker thread.
- While an operation is in flight, action buttons are disabled to prevent
  overlapping serial access; they re-enable when the result is drained.

## Entry Points & Packaging

`pyproject.toml` `[project.scripts]`:
- `e32config = "e32config.__main__:main"` — TUI (unchanged).
- `e32config-gui = "e32config.gui:main"` — GUI (new).

`gui.py` exposes `run()` (constructs the window and calls `mainloop()`) and
`main()` (import-guarded wrapper returning an int, mirroring `__main__.main`, so a
missing `customtkinter` yields a friendly message instead of a traceback).

Dependencies (`[project].dependencies`): add `customtkinter>=5.2`. Both `textual`
and `customtkinter` stay as base dependencies so `pip install -e .` provides both
front-ends. The existing `ImportError` guards remain for friendly messages.

## Compilation

Single source of truth: `scripts/build.py` — a cross-platform Python script
(runs on Windows/macOS/Linux) that invokes PyInstaller for **both** binaries:

- **TUI/CLI:** `pyinstaller --onefile --name e32config src/e32config/__main__.py`
- **GUI:** `pyinstaller --onefile --windowed --name e32config-gui
  --collect-all customtkinter src/e32config/gui.py`
  - `--windowed` → no stray console window on Windows/macOS.
  - `--collect-all customtkinter` → bundles CustomTkinter's theme/asset JSON
    files; without this the compiled GUI fails to start (known PyInstaller gotcha).

Local build: `python scripts/build.py` → produces both binaries in `dist/`.
The script accepts an optional `--only {cli,gui}` selector.

CI (`.github/workflows/build.yml`): the existing `binary` job is updated to call
`python scripts/build.py` (installing `.[build]`) on each of the 3 OSes, producing
**both** binaries per OS. Artifacts (6 total = 2 binaries × 3 OSes) are uploaded;
on `v*` tags they are attached to the GitHub Release. Naming keeps the existing
`-linux-x86_64` / `-macos` / `-windows.exe` suffix scheme, prefixed per binary
(`e32config-*` and `e32config-gui-*`). The `test` job is unchanged.

## Error Handling

Same guarantees as the base design, now also in the GUI: port-open failure, read
timeout, and unexpected response length/header are surfaced in the log panel as a
clear message; the app never crashes. Worker-thread exceptions are captured and
delivered to the UI as a red log line (never propagate out of the thread). The
first post-connect command's AUX-busy timeout is handled by transport's existing
one-retry behavior.

## Testing

- `tests/test_protocol.py` — unchanged.
- `tests/test_uimodel.py` (NEW): `parse_int`/`parse_channel`/`parse_address`
  (valid, hex, out-of-range, empty), `channel_calc`/`address_calc` string + ok
  flag for representative and invalid inputs, and `describe` on the reference
  params. Pure/headless — no serial port, no display.
- GUI smoke test: import `e32config.gui` and confirm `main`/`run` exist without
  launching `mainloop()`. Kept minimal because widget interaction isn't unit-tested;
  parity logic lives in the tested `uimodel` layer.

## Project Layout (after this work)

```
src/e32config/
├── __init__.py
├── __main__.py        # TUI entry (unchanged)
├── protocol.py        # unchanged
├── transport.py       # unchanged
├── uimodel.py         # NEW — shared UI-agnostic helpers
├── app.py             # TUI, refactored to import from uimodel
└── gui.py             # NEW — CustomTkinter windowed GUI
scripts/
└── build.py           # NEW — builds both binaries (local + CI)
tests/
├── test_protocol.py   # unchanged
└── test_uimodel.py    # NEW
pyproject.toml         # + customtkinter dep, + e32config-gui script
.github/workflows/build.yml  # updated: build both binaries via scripts/build.py
README.md              # updated: document GUI + both binaries
```

## Rollout / Compatibility

Fully backward compatible: `e32config`, `python -m e32config`, and the TUI's
behavior are unchanged. All additions are new modules/entry points. The `uimodel`
extraction is behavior-preserving and covered by the existing protocol tests plus
the new `uimodel` tests.
