#!/usr/bin/env python3
"""
BioPayload Command Center

Full-featured ground station GUI for the BioPayload ESP32 firmware (Phase 2).
Exposes every 1st-order command from COMMAND_REFERENCE.md, plus:
  - Live dual-line chart: 590 nm (f6) and 630 nm (f7) spectral channels
  - Continuous-stream mode: fires SPEC_READ back-to-back for calibration
  - Hover tooltip on the graph showing motor position at each datapoint
  - Live SYS_STATUS display, auto-polled every 2 s
  - Live motor position display, auto-polled every 1 s
  - Raw serial console (all RX / TX lines)

Serial: 115200 8N1, newline-delimited (same as pio device monitor).
"""

import json
import re
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import serial
import serial.tools.list_ports


# ---------------------------------------------------------------------------
# Serial helpers
# ---------------------------------------------------------------------------

def get_serial_ports() -> list[str]:
    ports = []
    for p in serial.tools.list_ports.comports():
        if "Bluetooth" not in p.description and "debug" not in p.device:
            ports.append(p.device)
    return sorted(ports)


class BoardSerial:
    """Background-reader serial wrapper (mirrors wellplate_gui.py pattern)."""

    def __init__(self, on_line, baudrate: int = 115200):
        self.on_line  = on_line
        self.baudrate = baudrate
        self._ser: Optional[serial.Serial] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, port: str) -> bool:
        try:
            self._ser = serial.Serial(port, self.baudrate, timeout=0.1)
            time.sleep(2)
            self._ser.reset_input_buffer()
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            return True
        except serial.SerialException as exc:
            self.on_line(f"ERR serial: {exc}")
            return False

    def disconnect(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    def send(self, cmd: str):
        if not self.connected:
            return
        try:
            line = (cmd + "\n") if not cmd.endswith("\n") else cmd
            self._ser.write(line.encode())
        except serial.SerialException:
            pass

    def _read_loop(self):
        buf = ""
        while self._running and self._ser and self._ser.is_open:
            try:
                if self._ser.in_waiting:
                    buf += self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            self.on_line(line)
                else:
                    time.sleep(0.01)
            except serial.SerialException:
                break


# ---------------------------------------------------------------------------
# Line parsers
# ---------------------------------------------------------------------------

_TELEM_RE = re.compile(r'^TELEM \{(.+)\}$')
_SYS_RE   = re.compile(
    r'SYS_STATUS pump:(\S+) motor:(\S+) led:(\S+) '
    r'limit:(\S+) spec:(\S+) sd:(\S+) state:(\S+)')
_POS_RE   = re.compile(r'^MOT_POS (-?\d+)$')


def parse_telem(line: str) -> Optional[dict]:
    """TELEM {"f1":N,...} → dict; keys f1–f8, clear, nir (all ints)."""
    m = _TELEM_RE.match(line)
    if not m:
        return None
    try:
        return json.loads("{" + m.group(1) + "}")
    except json.JSONDecodeError:
        return None


def parse_sys_status(line: str) -> Optional[dict]:
    m = _SYS_RE.search(line)
    if not m:
        return None
    return dict(zip(("pump", "motor", "led", "limit", "spec", "sd", "state"),
                    m.groups()))


def parse_mot_pos(line: str) -> Optional[int]:
    m = _POS_RE.match(line)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class CommandGUI:

    # Dark theme colors (mirrors main.py / wellplate_gui.py)
    C = {
        "bg":       "#121212",
        "panel":    "#1e1e1e",
        "accent":   "#2d2d2d",
        "border":   "#333333",
        "text":     "#e0e0e0",
        "dim":      "#888888",
        "success":  "#4caf50",
        "warning":  "#ff9800",
        "error":    "#f44336",
        "tx":       "#82aaff",
        "rx":       "#c3e88d",
        "c590":     "#ff6f00",   # orange  – 590 nm line
        "c630":     "#ce93d8",   # lilac   – 630 nm line
        "cclr":     "#4dd0e1",   # cyan    – clear channel line
        "graph_bg": "#1a1a2e",
        "graph_gd": "#2a2a3e",
        "pos_bar":  "#29b6f6",
    }

    MAX_PTS     = 300
    SYS_POLL_MS = 2000   # how often SYS_STATUS is auto-sent
    POS_POLL_MS = 1000   # how often MOT_POS is auto-sent

    # -------------------------------------------------------------------------

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("BioPayload Command Center")
        root.geometry("1360x940")
        root.minsize(1120, 780)
        root.configure(bg=self.C["bg"])

        self.board       = BoardSerial(self._on_line)
        self._connected  = False
        self._start_time: Optional[float] = None
        self._motor_pos  = 0

        # Spectral data buffers for live graph
        self._ts    : deque[float] = deque(maxlen=self.MAX_PTS)
        self._d590  : deque[float] = deque(maxlen=self.MAX_PTS)
        self._d630  : deque[float] = deque(maxlen=self.MAX_PTS)
        self._dclr  : deque[float] = deque(maxlen=self.MAX_PTS)
        self._pos_at: deque[int]   = deque(maxlen=self.MAX_PTS)  # motor pos per sample

        # Continuous-stream mode
        self._streaming        = False
        self._stream_after: Optional[str] = None  # scheduled next-read after ID

        # Hover tooltip state
        self._hover_idx: Optional[int] = None
        self._last_hover_ms = 0.0

        self._sys_after: Optional[str] = None
        self._pos_after: Optional[str] = None

        self._setup_styles()
        self._build_ui()
        self._log("BioPayload Command Center ready", "info")

    # -------------------------------------------------------------------------
    # Styles
    # -------------------------------------------------------------------------

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        C = self.C
        s.configure("Panel.TFrame",    background=C["panel"])
        s.configure("Dark.TFrame",     background=C["bg"])
        s.configure("Title.TLabel",    background=C["panel"], foreground=C["text"],
                    font=("Helvetica", 11, "bold"))
        s.configure("Dim.TLabel",      background=C["panel"], foreground=C["dim"],
                    font=("Helvetica", 10))
        s.configure("Header.TLabel",   background=C["bg"],    foreground=C["text"],
                    font=("Helvetica", 18, "bold"))
        s.configure("Primary.TButton", font=("Helvetica", 10, "bold"), padding=(10, 6))
        s.configure("Connect.TButton", font=("Helvetica", 10),         padding=(10, 5))
        s.configure("Small.TButton",   font=("Helvetica", 9),          padding=(6, 4))

    # -------------------------------------------------------------------------
    # Top-level layout
    # -------------------------------------------------------------------------

    def _build_ui(self):
        main = ttk.Frame(self.root, style="Dark.TFrame", padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_header(main)

        body = ttk.Frame(main, style="Dark.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        body.columnconfigure(0, weight=0, minsize=340)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left: scrollable control panels
        left_outer = ttk.Frame(body, style="Dark.TFrame")
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_left_scroll(left_outer)

        # Right: graph / status / console (grid with weights)
        right = ttk.Frame(body, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=4)   # graph  – most space
        right.rowconfigure(1, weight=1)   # status – compact
        right.rowconfigure(2, weight=2)   # console
        right.columnconfigure(0, weight=1)

        self._build_graph_panel(right)
        self._build_status_panel(right)
        self._build_console_panel(right)

    # -------------------------------------------------------------------------
    # Header
    # -------------------------------------------------------------------------

    def _build_header(self, parent):
        hdr = ttk.Frame(parent, style="Dark.TFrame")
        hdr.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(hdr, text="BioPayload Command Center",
                  style="Header.TLabel").pack(side=tk.LEFT)

        tk.Label(hdr, text="phase-2 v0.1",
                 bg=self.C["accent"], fg=self.C["dim"],
                 font=("Helvetica", 9), padx=8, pady=2).pack(side=tk.RIGHT)

        self._abort_btn = tk.Button(
            hdr, text="■  ABORT",
            bg="#b71c1c", fg="white", activebackground="#d32f2f",
            font=("Helvetica", 12, "bold"),
            padx=16, pady=6, relief=tk.FLAT, cursor="hand2",
            command=lambda: self._send("ABORT"))
        self._abort_btn.pack(side=tk.RIGHT, padx=(0, 8))

    # -------------------------------------------------------------------------
    # Left scrollable column
    # -------------------------------------------------------------------------

    def _build_left_scroll(self, parent):
        canvas = tk.Canvas(parent, bg=self.C["bg"], highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas, style="Dark.TFrame")
        win   = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))

        # Bind mousewheel only while cursor is over the left panel
        def _scroll(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _scroll))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._build_conn_panel(inner)
        self._build_motor_panel(inner)
        self._build_pump_panel(inner)
        self._build_led_panel(inner)
        self._build_limit_panel(inner)
        self._build_spec_panel(inner)
        self._build_sd_panel(inner)

    # -------------------------------------------------------------------------
    # Left panel: Connection
    # -------------------------------------------------------------------------

    def _build_conn_panel(self, parent):
        p = self._lpanel(parent, "Connection")

        # Port selection row
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text="Port:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._port_var = tk.StringVar()
        self._port_cb  = ttk.Combobox(row, textvariable=self._port_var,
                                      state="readonly", width=18)
        self._port_cb.pack(side=tk.LEFT, padx=(6, 4), fill=tk.X, expand=True)
        ttk.Button(row, text="⟳", width=3, style="Small.TButton",
                   command=self._refresh_ports).pack(side=tk.LEFT)
        self._refresh_ports()

        # Connect / disconnect
        crow = ttk.Frame(p, style="Panel.TFrame")
        crow.pack(fill=tk.X)
        self._conn_btn = ttk.Button(crow, text="Connect",
                                    style="Connect.TButton",
                                    command=self._toggle_conn)
        self._conn_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._conn_dot = tk.Label(crow, text="●", bg=self.C["panel"],
                                  fg=self.C["error"], font=("Helvetica", 14))
        self._conn_dot.pack(side=tk.LEFT, padx=(8, 0))

        # Quick system buttons
        qrow = ttk.Frame(p, style="Panel.TFrame")
        qrow.pack(fill=tk.X, pady=(8, 0))
        for cmd in ("PING", "HELLO", "STATE", "SYS_STATUS"):
            ttk.Button(qrow, text=cmd, style="Small.TButton",
                       command=lambda c=cmd: self._send(c)).pack(
                           side=tk.LEFT, expand=True, fill=tk.X, padx=1)

    def _refresh_ports(self):
        pts = get_serial_ports()
        self._port_cb["values"] = pts if pts else ["No ports"]
        self._port_var.set(pts[0] if pts else "No ports")

    def _toggle_conn(self):
        if self.board.connected:
            self._stop_stream()
            self._stop_poll()
            self.board.disconnect()
            self._connected = False
            self._conn_btn.configure(text="Connect")
            self._conn_dot.configure(fg=self.C["error"])
            self._log("Disconnected", "info")
        else:
            port = self._port_var.get()
            if not port or port == "No ports":
                messagebox.showerror("Error", "No port selected")
                return
            self._log(f"Connecting to {port}…", "info")
            if self.board.connect(port):
                self._connected = True
                self._start_time = time.time()
                self._conn_btn.configure(text="Disconnect")
                self._conn_dot.configure(fg=self.C["success"])
                self._log("Connected — sending HELLO", "success")
                self._send("HELLO")
                self._start_poll()
            else:
                self._log("Connection failed", "error")

    # -------------------------------------------------------------------------
    # Left panel: Motor
    # -------------------------------------------------------------------------

    def _build_motor_panel(self, parent):
        p = self._lpanel(parent, "Motor (Linear Actuator)")

        # MOT_MOVE <steps>
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row, text="Steps:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._mot_steps = tk.StringVar(value="100")
        ttk.Entry(row, textvariable=self._mot_steps,
                  width=8, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(row, text="MOT_MOVE", style="Small.TButton",
                   command=lambda: self._send(
                       f"MOT_MOVE {self._mot_steps.get().strip()}")).pack(side=tk.LEFT)

        # MOT_RUN FWD / REV / STOP
        row2 = ttk.Frame(p, style="Panel.TFrame")
        row2.pack(fill=tk.X, pady=(0, 4))
        for lbl, cmd in [("▶ FWD", "MOT_RUN FWD"),
                          ("◀ REV", "MOT_RUN REV"),
                          ("■ STOP", "MOT_STOP")]:
            ttk.Button(row2, text=lbl, style="Small.TButton",
                       command=lambda c=cmd: self._send(c)).pack(
                           side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # MOT_HOME / ENABLE / DISABLE
        row3 = ttk.Frame(p, style="Panel.TFrame")
        row3.pack(fill=tk.X, pady=(0, 4))
        for lbl, cmd in [("HOME", "MOT_HOME"),
                          ("ENABLE", "MOT_ENABLE"),
                          ("DISABLE", "MOT_DISABLE")]:
            ttk.Button(row3, text=lbl, style="Small.TButton",
                       command=lambda c=cmd: self._send(c)).pack(
                           side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # MOT_INTERVAL <us>
        row4 = ttk.Frame(p, style="Panel.TFrame")
        row4.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row4, text="Interval (µs):", style="Dim.TLabel").pack(side=tk.LEFT)
        self._mot_interval = tk.StringVar(value="120")
        ttk.Entry(row4, textvariable=self._mot_interval,
                  width=7, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(row4, text="SET", style="Small.TButton",
                   command=lambda: self._send(
                       f"MOT_INTERVAL {self._mot_interval.get().strip()}")).pack(side=tk.LEFT)
        ttk.Label(row4, text="(10–100000)", style="Dim.TLabel").pack(side=tk.LEFT, padx=(6, 0))

        # MOT_STATUS / MOT_POS
        row5 = ttk.Frame(p, style="Panel.TFrame")
        row5.pack(fill=tk.X)
        for cmd in ("MOT_STATUS", "MOT_POS"):
            ttk.Button(row5, text=cmd, style="Small.TButton",
                       command=lambda c=cmd: self._send(c)).pack(
                           side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    # -------------------------------------------------------------------------
    # Left panel: Pump
    # -------------------------------------------------------------------------

    def _build_pump_panel(self, parent):
        p = self._lpanel(parent, "Peristaltic Pump")

        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row, text="ms:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._pump_ms = tk.StringVar(value="1000")
        ttk.Entry(row, textvariable=self._pump_ms,
                  width=8, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(row, text="PUMP_RUN", style="Small.TButton",
                   command=lambda: self._send(
                       f"PUMP_RUN {self._pump_ms.get().strip()}")).pack(side=tk.LEFT)

        row2 = ttk.Frame(p, style="Panel.TFrame")
        row2.pack(fill=tk.X)
        for lbl, cmd in [("ON", "PUMP_ON"), ("OFF", "PUMP_OFF"), ("STATUS", "PUMP_STATUS")]:
            ttk.Button(row2, text=lbl, style="Small.TButton",
                       command=lambda c=cmd: self._send(c)).pack(
                           side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    # -------------------------------------------------------------------------
    # Left panel: LED
    # -------------------------------------------------------------------------

    def _build_led_panel(self, parent):
        p = self._lpanel(parent, "RGB LED")

        preview_row = ttk.Frame(p, style="Panel.TFrame")
        preview_row.pack(fill=tk.X, pady=(0, 6))

        self._led_preview = tk.Canvas(preview_row, width=44, height=44,
                                      bg="#000000", highlightthickness=1,
                                      highlightbackground=self.C["border"])
        self._led_preview.pack(side=tk.LEFT, padx=(0, 10))

        sliders = ttk.Frame(preview_row, style="Panel.TFrame")
        sliders.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._r_var = tk.IntVar(value=255)
        self._g_var = tk.IntVar(value=0)
        self._b_var = tk.IntVar(value=0)

        for label, var, fg in [("R", self._r_var, "#f44336"),
                                ("G", self._g_var, "#4caf50"),
                                ("B", self._b_var, "#42a5f5")]:
            r = ttk.Frame(sliders, style="Panel.TFrame")
            r.pack(fill=tk.X, pady=1)
            tk.Label(r, text=label, bg=self.C["panel"], fg=fg,
                     font=("Helvetica", 9, "bold"), width=2).pack(side=tk.LEFT)
            tk.Scale(r, from_=0, to=255, orient=tk.HORIZONTAL, variable=var,
                     bg=self.C["panel"], fg=self.C["dim"],
                     troughcolor=self.C["accent"], highlightthickness=0, length=130,
                     command=lambda _v: self._update_led_preview()).pack(
                         side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(r, textvariable=var, bg=self.C["panel"], fg=self.C["dim"],
                     font=("Consolas", 9), width=4).pack(side=tk.LEFT)

        self._update_led_preview()

        btns = ttk.Frame(p, style="Panel.TFrame")
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="LED_SET", style="Small.TButton",
                   command=self._cmd_led_set).pack(
                       side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        ttk.Button(btns, text="LED_OFF", style="Small.TButton",
                   command=lambda: self._send("LED_OFF")).pack(
                       side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="STATUS", style="Small.TButton",
                   command=lambda: self._send("LED_STATUS")).pack(
                       side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

    def _update_led_preview(self):
        r, g, b = self._r_var.get(), self._g_var.get(), self._b_var.get()
        self._led_preview.configure(bg=f"#{r:02x}{g:02x}{b:02x}")

    def _cmd_led_set(self):
        self._send(f"LED_SET {self._r_var.get()} {self._g_var.get()} {self._b_var.get()}")

    # -------------------------------------------------------------------------
    # Left panel: Limit switch
    # -------------------------------------------------------------------------

    def _build_limit_panel(self, parent):
        p = self._lpanel(parent, "Limit Switch")
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X)
        ttk.Button(row, text="LIM_STATUS", style="Small.TButton",
                   command=lambda: self._send("LIM_STATUS")).pack(side=tk.LEFT)
        self._lim_lbl = tk.Label(row, text="--", bg=self.C["panel"],
                                  fg=self.C["dim"], font=("Consolas", 12, "bold"))
        self._lim_lbl.pack(side=tk.LEFT, padx=(12, 0))

    # -------------------------------------------------------------------------
    # Left panel: Spectral sensor
    # -------------------------------------------------------------------------

    def _build_spec_panel(self, parent):
        p = self._lpanel(parent, "Spectral Sensor (AS7341)")

        ttk.Button(p, text="SPEC_READ  (≈250 ms)", style="Primary.TButton",
                   command=lambda: self._send("SPEC_READ")).pack(fill=tk.X, pady=(0, 6))

        # SPEC_GAIN / SPEC_ATIME with spinboxes
        spec_params = [
            ("Gain  (0–10):",   "_spec_gain",  5,   0,     10,    "SPEC_GAIN"),
            ("ATIME (0–255):",  "_spec_atime", 29,  0,     255,   "SPEC_ATIME"),
        ]
        for label, attr, default, lo, hi, cmd in spec_params:
            row = ttk.Frame(p, style="Panel.TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, style="Dim.TLabel", width=14).pack(side=tk.LEFT)
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            ttk.Spinbox(row, from_=lo, to=hi, textvariable=var,
                        width=6, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(4, 4))
            ttk.Button(row, text="Set", style="Small.TButton",
                       command=lambda v=var, c=cmd: self._send(
                           f"{c} {v.get()}")).pack(side=tk.LEFT)

        # SPEC_ASTEP (wider range)
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="ASTEP (0–65535):", style="Dim.TLabel", width=14).pack(side=tk.LEFT)
        self._spec_astep = tk.IntVar(value=599)
        ttk.Spinbox(row, from_=0, to=65535, textvariable=self._spec_astep,
                    width=7, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(row, text="Set", style="Small.TButton",
                   command=lambda: self._send(
                       f"SPEC_ASTEP {self._spec_astep.get()}")).pack(side=tk.LEFT)

        ttk.Button(p, text="SPEC_STATUS", style="Small.TButton",
                   command=lambda: self._send("SPEC_STATUS")).pack(anchor=tk.W, pady=(6, 0))

    # -------------------------------------------------------------------------
    # Left panel: SD card
    # -------------------------------------------------------------------------

    def _build_sd_panel(self, parent):
        p = self._lpanel(parent, "SD Card")

        ttk.Button(p, text="SD_STATUS", style="Small.TButton",
                   command=lambda: self._send("SD_STATUS")).pack(anchor=tk.W, pady=(0, 6))

        row1 = ttk.Frame(p, style="Panel.TFrame")
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Path:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._sd_list_path = tk.StringVar(value="/")
        ttk.Entry(row1, textvariable=self._sd_list_path,
                  width=10, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Button(row1, text="SD_LIST", style="Small.TButton",
                   command=lambda: self._send(
                       f"SD_LIST {self._sd_list_path.get().strip()}")).pack(side=tk.LEFT)

        row2 = ttk.Frame(p, style="Panel.TFrame")
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="File:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._sd_del_path = tk.StringVar(value="/events.log")
        ttk.Entry(row2, textvariable=self._sd_del_path,
                  width=14, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Button(row2, text="SD_DELETE", style="Small.TButton",
                   command=self._cmd_sd_delete).pack(side=tk.LEFT)

    def _cmd_sd_delete(self):
        path = self._sd_del_path.get().strip()
        if path and messagebox.askyesno("Confirm Delete", f"Delete {path}?"):
            self._send(f"SD_DELETE {path}")

    # -------------------------------------------------------------------------
    # Right panel: Live spectral graph
    # -------------------------------------------------------------------------

    def _build_graph_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        p = ttk.Frame(container, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.BOTH, expand=True)

        ttk.Label(p, text="Live Spectral — 590 nm, 630 nm & Clear",
                  style="Title.TLabel").pack(anchor=tk.W, pady=(0, 6))

        toolbar = ttk.Frame(p, style="Panel.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 4))

        self._lbl590 = tk.Label(toolbar, text="590 nm: --",
                                bg=self.C["panel"], fg=self.C["c590"],
                                font=("Consolas", 12, "bold"))
        self._lbl590.pack(side=tk.LEFT, padx=(0, 20))

        self._lbl630 = tk.Label(toolbar, text="630 nm: --",
                                bg=self.C["panel"], fg=self.C["c630"],
                                font=("Consolas", 12, "bold"))
        self._lbl630.pack(side=tk.LEFT, padx=(0, 20))

        self._lblclr = tk.Label(toolbar, text="Clear: --",
                                bg=self.C["panel"], fg=self.C["cclr"],
                                font=("Consolas", 12, "bold"))
        self._lblclr.pack(side=tk.LEFT, padx=(0, 20))

        self._lbl_n = tk.Label(toolbar, text="n=0",
                               bg=self.C["panel"], fg=self.C["dim"],
                               font=("Consolas", 10))
        self._lbl_n.pack(side=tk.LEFT)

        # Right-side buttons
        ttk.Button(toolbar, text="Clear", style="Small.TButton",
                   command=self._clear_graph).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="SPEC_READ", style="Small.TButton",
                   command=lambda: self._send("SPEC_READ")).pack(side=tk.RIGHT, padx=(4, 0))

        # Stream toggle button (styled separately so we can recolor it)
        self._stream_btn = tk.Button(
            toolbar, text="▶  Start Stream",
            bg=self.C["accent"], fg=self.C["text"],
            activebackground=self.C["border"],
            font=("Helvetica", 9, "bold"),
            padx=10, pady=3, relief=tk.FLAT, cursor="hand2",
            command=self._toggle_stream)
        self._stream_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self._fig = Figure(figsize=(5, 3), dpi=100, facecolor=self.C["graph_bg"])
        self._ax  = self._fig.add_subplot(111)
        self._style_ax()
        self._fig_canvas = FigureCanvasTkAgg(self._fig, master=p)
        self._fig_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Connect hover event for tooltip
        self._fig_canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _style_ax(self):
        ax, C = self._ax, self.C
        ax.set_facecolor(C["graph_bg"])
        ax.tick_params(colors=C["dim"], labelsize=8)
        ax.set_xlabel("Time (s)", color=C["dim"], fontsize=9)
        ax.set_ylabel("Counts", color=C["dim"], fontsize=9)
        for sp in ax.spines.values():
            sp.set_color(C["graph_gd"])
        ax.grid(True, color=C["graph_gd"], linewidth=0.4, alpha=0.6)

    # ---- streaming ----------------------------------------------------------

    def _toggle_stream(self):
        if self._streaming:
            self._stop_stream()
        else:
            if not self.board.connected:
                self._log("Not connected", "warning")
                return
            self._streaming = True
            self._stream_btn.configure(
                text="■  Stop Stream",
                bg="#b71c1c", fg="white", activebackground="#d32f2f")
            self._log("Spectral stream started", "success")
            self._send("SPEC_READ")

    def _stop_stream(self):
        self._streaming = False
        if self._stream_after:
            self.root.after_cancel(self._stream_after)
            self._stream_after = None
        if hasattr(self, "_stream_btn"):
            self._stream_btn.configure(
                text="▶  Start Stream",
                bg=self.C["accent"], fg=self.C["text"],
                activebackground=self.C["border"])

    # ---- data push & graph --------------------------------------------------

    def _push_telem(self, data: dict):
        if self._start_time is None:
            self._start_time = time.time()
        t   = time.time() - self._start_time
        v59 = data.get("f6", 0)
        v63 = data.get("f7", 0)
        vcl = data.get("clear", 0)
        self._ts.append(t)
        self._d590.append(v59)
        self._d630.append(v63)
        self._dclr.append(vcl)
        self._pos_at.append(self._motor_pos)   # snapshot position at this sample
        self._lbl590.configure(text=f"590 nm: {v59}")
        self._lbl630.configure(text=f"630 nm: {v63}")
        self._lblclr.configure(text=f"Clear: {vcl}")
        self._lbl_n.configure(text=f"n={len(self._ts)}")
        self._redraw_graph()
        # Fire next read if streaming (small delay lets the ESP32 dispatcher breathe)
        if self._streaming and self.board.connected:
            self._stream_after = self.root.after(
                30, lambda: self._send("SPEC_READ") if self._streaming else None)

    def _redraw_graph(self):
        ax, C = self._ax, self.C
        ax.cla()
        self._style_ax()
        xs = y59 = y63 = ycl = []
        if self._ts:
            xs  = list(self._ts)
            y59 = list(self._d590)
            y63 = list(self._d630)
            ycl = list(self._dclr)
            ax.plot(xs, y59, color=C["c590"], linewidth=1.4, label="590 nm")
            ax.fill_between(xs, y59, color=C["c590"], alpha=0.08)
            ax.plot(xs, y63, color=C["c630"], linewidth=1.4, label="630 nm")
            ax.fill_between(xs, y63, color=C["c630"], alpha=0.08)
            ax.plot(xs, ycl, color=C["cclr"], linewidth=1.2, label="Clear", linestyle="--")
            ax.legend(fontsize=8, facecolor=C["graph_bg"],
                      labelcolor=C["dim"], framealpha=0.7)
            all_v = y59 + y63 + ycl
            lo, hi = max(0, min(all_v) - 50), max(all_v) + 50
            if lo == hi:
                lo -= 50
                hi += 50
            ax.set_ylim(lo, hi)

        # Hover annotation
        idx = self._hover_idx
        if idx is not None and xs and 0 <= idx < len(xs):
            hx   = xs[idx]
            hy59 = y59[idx]
            hy63 = y63[idx]
            hycl = ycl[idx] if idx < len(ycl) else "?"
            hpos = list(self._pos_at)[idx] if idx < len(self._pos_at) else "?"
            # Vertical cursor line
            ax.axvline(hx, color=C["dim"], linewidth=0.8, linestyle="--", alpha=0.6)
            # Dot markers on each line
            ax.plot(hx, hy59, "o", color=C["c590"], markersize=6, zorder=5)
            ax.plot(hx, hy63, "o", color=C["c630"], markersize=6, zorder=5)
            ax.plot(hx, hycl, "o", color=C["cclr"],  markersize=6, zorder=5)
            # Annotation box — flip side if near right edge
            ax_w = ax.get_xlim()[1] - ax.get_xlim()[0] if ax.get_xlim()[1] != ax.get_xlim()[0] else 1
            x_frac = (hx - ax.get_xlim()[0]) / ax_w if ax_w else 0.5
            x_offset = -120 if x_frac > 0.75 else 12
            y_anchor = max(hy59, hy63, hycl) if isinstance(hycl, (int, float)) else max(hy59, hy63)
            ax.annotate(
                f"t = {hx:.2f} s\n590 = {hy59}\n630 = {hy63}\nclr = {hycl}\npos = {hpos} steps",
                xy=(hx, y_anchor),
                xytext=(x_offset, 8),
                textcoords="offset points",
                color=C["text"],
                fontsize=8,
                bbox=dict(boxstyle="round,pad=0.4",
                          facecolor=C["panel"],
                          edgecolor=C["border"],
                          alpha=0.92),
                arrowprops=dict(arrowstyle="->", color=C["dim"], lw=0.8),
                zorder=10,
            )

        self._fig.tight_layout(pad=0.8)
        self._fig_canvas.draw_idle()

    def _clear_graph(self):
        self._ts.clear()
        self._d590.clear()
        self._d630.clear()
        self._dclr.clear()
        self._pos_at.clear()
        self._hover_idx = None
        self._redraw_graph()
        self._lbl590.configure(text="590 nm: --")
        self._lbl630.configure(text="630 nm: --")
        self._lblclr.configure(text="Clear: --")
        self._lbl_n.configure(text="n=0")

    # ---- hover tooltip ------------------------------------------------------

    def _on_hover(self, event):
        """Update hover annotation when mouse moves over the axes."""
        if not event.inaxes or not self._ts:
            if self._hover_idx is not None:
                self._hover_idx = None
                self._redraw_graph()
            return

        xs = list(self._ts)
        # Find nearest sample by x distance
        new_idx = min(range(len(xs)), key=lambda i: abs(xs[i] - event.xdata))

        if new_idx == self._hover_idx:
            return   # same point — nothing to do

        self._hover_idx = new_idx

        # Throttle redraws to ~30 fps so hovering stays responsive during streaming
        now_ms = time.time() * 1000
        if now_ms - self._last_hover_ms < 33:
            return
        self._last_hover_ms = now_ms
        self._redraw_graph()

    # -------------------------------------------------------------------------
    # Right panel: Live system status + motor position
    # -------------------------------------------------------------------------

    def _build_status_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        p = ttk.Frame(container, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.BOTH, expand=True)

        ttk.Label(p, text="Live System Status  (auto-updates every 1–2 s)",
                  style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))

        top = ttk.Frame(p, style="Panel.TFrame")
        top.pack(fill=tk.X, pady=(0, 8))

        # State
        state_box = ttk.Frame(top, style="Panel.TFrame")
        state_box.pack(side=tk.LEFT, padx=(0, 24))
        ttk.Label(state_box, text="STATE", style="Dim.TLabel").pack(anchor=tk.W)
        self._state_lbl = tk.Label(state_box, text="--",
                                   bg=self.C["panel"], fg=self.C["dim"],
                                   font=("Helvetica", 22, "bold"))
        self._state_lbl.pack(anchor=tk.W)

        # Motor position (large number)
        pos_box = ttk.Frame(top, style="Panel.TFrame")
        pos_box.pack(side=tk.LEFT, padx=(0, 24))
        ttk.Label(pos_box, text="MOTOR POSITION (steps)", style="Dim.TLabel").pack(anchor=tk.W)
        self._pos_lbl = tk.Label(pos_box, text="--",
                                 bg=self.C["panel"], fg=self.C["pos_bar"],
                                 font=("Consolas", 22, "bold"))
        self._pos_lbl.pack(anchor=tk.W)

        # Position bar (−5000 … +5000)
        bar_box = ttk.Frame(top, style="Panel.TFrame")
        bar_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(bar_box, text="Position bar  (−5000 … +5000)",
                  style="Dim.TLabel").pack(anchor=tk.W)
        self._pos_canvas = tk.Canvas(bar_box, height=22,
                                     bg=self.C["accent"], highlightthickness=0)
        self._pos_canvas.pack(fill=tk.X, pady=(4, 0))
        self._pos_canvas.bind("<Configure>", lambda _e: self._draw_pos_bar())

        # Per-component indicators
        comp_row = ttk.Frame(p, style="Panel.TFrame")
        comp_row.pack(fill=tk.X)
        self._comp_lbls: dict[str, tk.Label] = {}
        for name in ("pump", "motor", "led", "limit", "spec", "sd"):
            box = ttk.Frame(comp_row, style="Panel.TFrame")
            box.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
            ttk.Label(box, text=name.upper(), style="Dim.TLabel").pack()
            lbl = tk.Label(box, text="--", bg=self.C["panel"], fg=self.C["dim"],
                           font=("Consolas", 10, "bold"))
            lbl.pack()
            self._comp_lbls[name] = lbl

    def _update_sys_status(self, data: dict):
        state_fg = {
            "IDLE":     self.C["dim"],
            "PRIMING":  self.C["warning"],
            "ACTIVE":   self.C["success"],
            "SCANNING": "#29b6f6",
            "DONE":     "#64b5f6",
            "ERROR":    self.C["error"],
        }
        val_fg = {
            "RUNNING":   self.C["success"],
            "MOVING":    self.C["warning"],
            "HOMING":    self.C["warning"],
            "ON":        self.C["success"],
            "CLOSED":    self.C["warning"],
            "READY":     self.C["success"],
            "IDLE":      self.C["dim"],
            "OFF":       self.C["dim"],
            "OPEN":      self.C["dim"],
            "NOT_FOUND": self.C["error"],
        }
        state = data.get("state", "--")
        self._state_lbl.configure(text=state,
                                   fg=state_fg.get(state, self.C["text"]))
        for name in ("pump", "motor", "led", "limit", "spec", "sd"):
            val = data.get(name, "--")
            self._comp_lbls[name].configure(
                text=val, fg=val_fg.get(val, self.C["text"]))

    def _update_mot_pos(self, pos: int):
        self._motor_pos = pos
        self._pos_lbl.configure(text=str(pos))
        self._draw_pos_bar()

    def _draw_pos_bar(self):
        w = self._pos_canvas.winfo_width()
        if w <= 1:
            return
        self._pos_canvas.delete("all")
        POS_MAX = 5000
        frac = (self._motor_pos + POS_MAX) / (2 * POS_MAX)
        frac = max(0.0, min(1.0, frac))
        cx  = int(frac * w)
        mid = w // 2
        # Filled bar from centre to current position
        self._pos_canvas.create_rectangle(
            min(cx, mid), 1, max(cx, mid), 21,
            fill=self.C["pos_bar"], outline="")
        # Position marker
        self._pos_canvas.create_rectangle(cx - 2, 0, cx + 2, 22,
                                           fill="white", outline="")
        # Centre tick
        self._pos_canvas.create_rectangle(mid - 1, 0, mid + 1, 22,
                                           fill=self.C["dim"], outline="")

    # -------------------------------------------------------------------------
    # Right panel: Serial console
    # -------------------------------------------------------------------------

    def _build_console_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=2, column=0, sticky="nsew")
        p = ttk.Frame(container, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.BOTH, expand=True)

        ttk.Label(p, text="Serial Console", style="Title.TLabel").pack(
            anchor=tk.W, pady=(0, 6))

        # Manual TX row
        tx_row = ttk.Frame(p, style="Panel.TFrame")
        tx_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(tx_row, text="TX:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._manual_var = tk.StringVar()
        entry = ttk.Entry(tx_row, textvariable=self._manual_var,
                          font=("Consolas", 10))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))
        entry.bind("<Return>", lambda _e: self._manual_send())
        ttk.Button(tx_row, text="Send", style="Small.TButton",
                   command=self._manual_send).pack(side=tk.LEFT)
        ttk.Button(tx_row, text="Clear", style="Small.TButton",
                   command=self._clear_console).pack(side=tk.LEFT, padx=(4, 0))

        frame = ttk.Frame(p, style="Panel.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        self._console = tk.Text(frame, bg=self.C["bg"], fg=self.C["dim"],
                                font=("Consolas", 9), state=tk.DISABLED,
                                wrap=tk.NONE)
        vsb = ttk.Scrollbar(frame, orient="vertical",
                             command=self._console.yview)
        self._console.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for tag, color in [("tx",      self.C["tx"]),
                            ("rx",      self.C["rx"]),
                            ("info",    self.C["text"]),
                            ("success", self.C["success"]),
                            ("warning", self.C["warning"]),
                            ("error",   self.C["error"])]:
            self._console.tag_configure(tag, foreground=color)

    def _manual_send(self):
        cmd = self._manual_var.get().strip()
        if cmd:
            self._send(cmd)
            self._manual_var.set("")

    def _clear_console(self):
        self._console.configure(state=tk.NORMAL)
        self._console.delete("1.0", tk.END)
        self._console.configure(state=tk.DISABLED)

    # -------------------------------------------------------------------------
    # Auto-polling
    # -------------------------------------------------------------------------

    def _start_poll(self):
        self._poll_sys()
        self._poll_pos()

    def _stop_poll(self):
        for attr in ("_sys_after", "_pos_after"):
            aid = getattr(self, attr, None)
            if aid:
                self.root.after_cancel(aid)
                setattr(self, attr, None)
        self._stop_stream()

    def _poll_sys(self):
        if self._connected and self.board.connected:
            self.board.send("SYS_STATUS")
        self._sys_after = self.root.after(self.SYS_POLL_MS, self._poll_sys)

    def _poll_pos(self):
        if self._connected and self.board.connected:
            self.board.send("MOT_POS")
        self._pos_after = self.root.after(self.POS_POLL_MS, self._poll_pos)

    # -------------------------------------------------------------------------
    # Serial I/O
    # -------------------------------------------------------------------------

    def _send(self, cmd: str):
        if not self.board.connected:
            self._log("Not connected", "warning")
            return
        self.board.send(cmd)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._console.configure(state=tk.NORMAL)
        self._console.insert(tk.END, f"{ts}  TX → {cmd}\n", "tx")
        self._console.see(tk.END)
        self._console.configure(state=tk.DISABLED)

    def _on_line(self, line: str):
        """Called from background reader thread — schedule on main thread."""
        self.root.after(0, lambda: self._dispatch(line))

    def _dispatch(self, line: str):
        """
        Route one incoming line.
        SYS_STATUS and MOT_POS are consumed silently (update widgets only)
        to avoid flooding the console during auto-polling.
        Everything else appears in the console.
        """
        sys_data = parse_sys_status(line)
        if sys_data is not None:
            self._update_sys_status(sys_data)
            return

        pos = parse_mot_pos(line)
        if pos is not None:
            self._update_mot_pos(pos)
            return

        # All other lines → console
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._console.configure(state=tk.NORMAL)
        self._console.insert(tk.END, f"{ts}  RX ← {line}\n", "rx")
        self._console.see(tk.END)
        self._console.configure(state=tk.DISABLED)

        # TELEM → graph update
        telem = parse_telem(line)
        if telem is not None:
            self._push_telem(telem)
            return

        # ERR during streaming → stop stream so we don't loop forever
        if line.startswith("ERR") and self._streaming:
            self._stop_stream()
            self._log("Stream stopped due to error", "warning")
            return

        # LIM_STATUS → update limit label
        if line.startswith("LIM_STATUS "):
            val = line[11:].strip()
            self._lim_lbl.configure(
                text=val,
                fg=self.C["warning"] if val == "CLOSED" else self.C["dim"])
            return

        # STATE transition → also update the state label directly
        if line.startswith("STATE "):
            state = line[6:].strip()
            fg_map = {"IDLE":     self.C["dim"],
                      "PRIMING":  self.C["warning"],
                      "ACTIVE":   self.C["success"],
                      "SCANNING": "#29b6f6",
                      "DONE":     "#64b5f6",
                      "ERROR":    self.C["error"]}
            self._state_lbl.configure(text=state,
                                      fg=fg_map.get(state, self.C["text"]))

    # -------------------------------------------------------------------------
    # Logging helpers
    # -------------------------------------------------------------------------

    def _log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._console.configure(state=tk.NORMAL)
        self._console.insert(tk.END, f"[{ts}] {msg}\n", level)
        self._console.see(tk.END)
        self._console.configure(state=tk.DISABLED)

    # -------------------------------------------------------------------------
    # Panel factory: left column
    # -------------------------------------------------------------------------

    def _lpanel(self, parent, title: str) -> ttk.Frame:
        """Scrollable-left full-width panel with title."""
        c = ttk.Frame(parent, style="Dark.TFrame")
        c.pack(fill=tk.X, pady=(0, 8))
        p = ttk.Frame(c, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.X)
        ttk.Label(p, text=title, style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))
        return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app  = CommandGUI(root)
    root.protocol("WM_DELETE_WINDOW",
                  lambda: (app.board.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
