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
