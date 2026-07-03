"""Textual TUI for reading and writing E32-433T30D parameters."""

from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Select

from . import __version__, protocol
from .protocol import Params, ProtocolError
from .transport import (
    PortInfo, SerialTransport, TransportError, list_serial_ports,
)
from .uimodel import (
    ENUM_FIELDS, address_calc, channel_calc, describe, enum_options,
    parse_address, parse_channel,
)


class E32App(App):
    TITLE = "e32config"
    SUB_TITLE = f"E32-433T30D LoRa configurator v{__version__}"
    CSS = """
    #topbar { height: auto; padding: 0 1; }
    #topbar Select { width: 60%; }
    #topbar Button { width: auto; margin-left: 1; }
    #hint { color: $warning; padding: 0 1; }
    #status { padding: 0 1; }
    #form { height: auto; padding: 1; }
    .field { height: auto; width: 1fr; padding: 0 1; }
    .field Label { color: $text-muted; }
    .field Input { width: 100%; }
    .calc { color: $success; text-style: italic; }
    .calc-err { color: $error; text-style: italic; }
    #actions { height: auto; padding: 0 1; }
    #actions Button { margin-right: 1; }
    RichLog { height: 1fr; border: round $primary; margin: 1; }
    """

    BINDINGS = [
        ("r", "read", "Read"),
        ("s", "write_save", "Write (C0)"),
        ("t", "write_temp", "Write (C2)"),
        ("v", "version", "Version"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._transport: SerialTransport | None = None
        self._ports: list[PortInfo] = []
        self._confirm_reset = False

    # -- layout --------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        self._ports = list_serial_ports()
        port_opts = [(p.label, p.device) for p in self._ports] or [("<no ports found>", "")]
        with Horizontal(id="topbar"):
            yield Select(port_opts, id="port", prompt="Select serial port", allow_blank=True)
            yield Button("Connect", id="connect", variant="primary")
            yield Button("Refresh", id="refresh")
        yield Label("Set the module to Mode 3 (M0=1, M1=1) and wire RXD/TXD/GND before connecting.", id="hint")
        yield Label("Not connected.", id="status")

        with VerticalScroll(id="form"):
            # Enum dropdowns, two per row.
            for row_start in range(0, len(ENUM_FIELDS), 2):
                with Horizontal():
                    for wid, label, enum_cls, _attr in ENUM_FIELDS[row_start:row_start + 2]:
                        with Vertical(classes="field"):
                            yield Label(label)
                            yield Select(enum_options(enum_cls), id=wid, allow_blank=False)

            # Manually-typed channel + address (hex split is computed for you).
            with Horizontal():
                with Vertical(classes="field"):
                    yield Label("Channel (0–31, or 0x..)")
                    yield Input(value="23", id="channel", placeholder="e.g. 23")
                    yield Label("", id="channel_calc", classes="calc")
                with Vertical(classes="field"):
                    yield Label("Address (0–65535, or 0x..)")
                    yield Input(value="0", id="address", placeholder="e.g. 22")
                    yield Label("", id="addr_calc", classes="calc")

        with Horizontal(id="actions"):
            yield Button("Read (C1)", id="read", variant="success")
            yield Button("Write save (C0)", id="write_save", variant="warning")
            yield Button("Write temp (C2)", id="write_temp")
            yield Button("Version (C3)", id="version")
            yield Button("Reset (C4)", id="reset", variant="error")

        yield RichLog(id="log", markup=True, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self._update_channel_calc()
        self._update_addr_calc()
        self.log_line("[dim]Ready. Select a port and press Connect.[/dim]")

    # -- helpers -------------------------------------------------------------
    def log_line(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.query_one("#log", RichLog).write(f"[dim]{ts}[/dim] {msg}")

    def set_status(self, msg: str) -> None:
        self.query_one("#status", Label).update(msg)

    def _require_transport(self) -> SerialTransport | None:
        if self._transport is None:
            self.log_line("[red]Not connected. Press Connect first.[/red]")
            return None
        return self._transport

    # -- live calculation labels --------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "channel":
            self._update_channel_calc()
        elif event.input.id == "address":
            self._update_addr_calc()

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

    # -- form <-> Params -----------------------------------------------------
    def _load_params_into_form(self, p: Params) -> None:
        for wid, _label, _enum_cls, attr in ENUM_FIELDS:
            self.query_one(f"#{wid}", Select).value = int(getattr(p, attr))
        self.query_one("#channel", Input).value = str(p.channel)
        self.query_one("#address", Input).value = str(p.address)
        self._update_channel_calc()
        self._update_addr_calc()

    def _read_params_from_form(self) -> Params:
        vals: dict = {}
        for wid, _label, enum_cls, attr in ENUM_FIELDS:
            vals[attr] = enum_cls(int(self.query_one(f"#{wid}", Select).value))
        try:
            vals["channel"] = parse_channel(self.query_one("#channel", Input).value)
        except ValueError as exc:
            raise ProtocolError(f"Channel: {exc}") from exc
        try:
            addr = parse_address(self.query_one("#address", Input).value)
        except ValueError as exc:
            raise ProtocolError(f"Address: {exc}") from exc
        vals["addr_high"] = (addr >> 8) & 0xFF
        vals["addr_low"] = addr & 0xFF
        return Params(**vals)

    # -- button dispatch -----------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "connect": self.action_connect,
            "refresh": self.action_refresh,
            "read": self.action_read,
            "write_save": self.action_write_save,
            "write_temp": self.action_write_temp,
            "version": self.action_version,
            "reset": self.action_reset,
        }
        handler = handlers.get(event.button.id)
        if handler:
            handler()

    # -- actions -------------------------------------------------------------
    def action_refresh(self) -> None:
        self._ports = list_serial_ports()
        opts = [(p.label, p.device) for p in self._ports] or [("<no ports found>", "")]
        self.query_one("#port", Select).set_options(opts)
        self.log_line(f"Found {len(self._ports)} serial port(s).")

    def action_connect(self) -> None:
        device = self.query_one("#port", Select).value
        if not device:
            self.log_line("[red]No port selected.[/red]")
            return
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        try:
            self._transport = SerialTransport(device, baud=9600)
        except TransportError as exc:
            self.set_status("[red]Connection failed[/red]")
            self.log_line(f"[red]{exc}[/red]")
            return
        self.set_status(f"[green]Connected[/green] to {device} @ 9600 8N1")
        self.log_line(f"[green]Opened {device}[/green]. Press Read to fetch current params.")

    def action_read(self) -> None:
        t = self._require_transport()
        if not t:
            return
        try:
            self.log_line(f"[cyan]TX[/cyan] {protocol.READ_PARAMS.hex(' ')}")
            data = t.command(protocol.READ_PARAMS, protocol.PARAM_LEN, retries=1)
            self.log_line(f"[green]RX[/green] {data.hex(' ')}")
            params = protocol.decode_params(data)
            self._load_params_into_form(params)
            self.log_line(describe(params))
        except (TransportError, ProtocolError) as exc:
            self.log_line(f"[red]{exc}[/red]")

    def action_write_save(self) -> None:
        self._write(save=True)

    def action_write_temp(self) -> None:
        self._write(save=False)

    def _write(self, save: bool) -> None:
        t = self._require_transport()
        if not t:
            return
        try:
            params = self._read_params_from_form()
        except (ValueError, ProtocolError) as exc:
            self.log_line(f"[red]Invalid form values: {exc}[/red]")
            return
        frame = protocol.encode_params(params, save=save)
        kind = "C0 (persist)" if save else "C2 (temp)"
        self.log_line(f"[yellow]Writing {kind}[/yellow]  {describe(params)}")
        try:
            self.log_line(f"[cyan]TX[/cyan] {frame.hex(' ')}")
            echo = t.command(frame, protocol.PARAM_LEN, retries=1)
            self.log_line(f"[green]RX[/green] {echo.hex(' ')}")
        except (TransportError, ProtocolError) as exc:
            self.log_line(f"[red]{exc}[/red]")
            return
        # Verify by reading back.
        try:
            readback = t.command(protocol.READ_PARAMS, protocol.PARAM_LEN, retries=1)
            expected = bytes([protocol.HEAD_READBACK]) + frame[1:]
            if readback == expected:
                self.log_line("[green]Verified: module now matches the written config.[/green]")
            else:
                self.log_line(
                    f"[yellow]Mismatch after write.[/yellow] readback={readback.hex(' ')} "
                    f"expected={expected.hex(' ')}"
                )
        except (TransportError, ProtocolError) as exc:
            self.log_line(f"[yellow]Could not verify: {exc}[/yellow]")

    def action_version(self) -> None:
        t = self._require_transport()
        if not t:
            return
        try:
            self.log_line(f"[cyan]TX[/cyan] {protocol.READ_VERSION.hex(' ')}")
            data = t.command(protocol.READ_VERSION, protocol.VERSION_LEN, retries=1)
            self.log_line(f"[green]RX[/green] {data.hex(' ')}")
            ver = protocol.decode_version(data)
            self.log_line(f"[bold]{ver.label}[/bold]")
        except (TransportError, ProtocolError) as exc:
            self.log_line(f"[red]{exc}[/red]")

    def action_reset(self) -> None:
        t = self._require_transport()
        if not t:
            return
        if not self._confirm_reset:
            self._confirm_reset = True
            self.log_line("[red]Press Reset again within this session to confirm module reset.[/red]")
            return
        self._confirm_reset = False
        try:
            self.log_line(f"[cyan]TX[/cyan] {protocol.RESET.hex(' ')}")
            t.send(protocol.RESET)
            self.log_line("[yellow]Reset command sent. The module reboots and runs self-check.[/yellow]")
        except TransportError as exc:
            self.log_line(f"[red]{exc}[/red]")

    def on_unmount(self) -> None:
        if self._transport is not None:
            self._transport.close()


def run() -> None:
    E32App().run()
