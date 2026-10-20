#!/usr/bin/env python3
"""
BioPayload Demo GUI — proof-of-concept mockup.

Mirrors the look of command_gui.py but requires no Arduino.  The graph
area has tabs for each well and displays a simulated OD600-style logistic
growth curve.  The serial console is pre-populated with realistic output
from an experiment run.
"""

import math
import random
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Simulated data generators
# ---------------------------------------------------------------------------

def logistic(t, L, k, t0):
    return L / (1.0 + math.exp(-k * (t - t0)))


def generate_well_data(well_idx: int, n_scans: int = 20,
                       scan_interval_s: float = 120.0):
    """Return (times, f590, f630, clear) lists with a noisy S-curve."""
    random.seed(42 + well_idx)

    L    = 1800 + well_idx * 400
    k    = 0.0025 + well_idx * 0.0003
    t0   = 1200 + well_idx * 150
    base = 200 + well_idx * 60

    ts, f590, f630, clr = [], [], [], []
    for i in range(n_scans):
        t = i * scan_interval_s
        v = base + logistic(t, L, k, t0)
        noise = random.gauss(0, 25)
        ts.append(t)
        f590.append(int(v + noise))
        f630.append(int(v * 0.72 + random.gauss(0, 18)))
        clr.append(int(v * 1.15 + random.gauss(0, 30)))
    return ts, f590, f630, clr


WELL_POSITIONS = [14030, 62563, 109305, 157301]

N_SCANS        = 20
SCAN_INTERVAL  = 120.0
TOTAL_DURATION  = int(N_SCANS * SCAN_INTERVAL * 1000)

WELL_DATA = {}
for _i in range(4):
    WELL_DATA[_i] = generate_well_data(_i, N_SCANS, SCAN_INTERVAL)


def generate_console_lines():
    """Build a list of (tag, text) tuples mimicking a real experiment run."""
    lines: list[tuple[str, str]] = []
    t = datetime.now() - timedelta(seconds=N_SCANS * SCAN_INTERVAL + 30)

    def ts():
        return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"

    def rx(msg):
        lines.append(("rx", f"{ts()}  RX ← {msg}"))

    def tx(msg):
        lines.append(("tx", f"{ts()}  TX → {msg}"))

    def info(msg):
        lines.append(("info", f"[{t.strftime('%H:%M:%S')}] {msg}"))

    def success(msg):
        lines.append(("success", f"[{t.strftime('%H:%M:%S')}] {msg}"))

    # Boot
    info("BioPayload Command Center ready")
    info("Connecting to /dev/cu.usbmodemE4B063AF458C2…")
    t += timedelta(seconds=2.2)
    rx("[boot] pump  on pin 14 OK")
    rx("[boot] motor on (STEP=7,DIR=5,EN=6) OK")
    rx("[boot] led   on (R=5,G=4,B=6) OK")
    rx("[boot] limit on pin 46 OPEN")
    rx("[boot] spec  I2C 0x39 OK")
    rx("[boot] sd   on HSPI (CS=D7) OK")
    rx("STATE IDLE")
    success("Connected — sending HELLO")
    tx("HELLO")
    t += timedelta(milliseconds=50)
    rx("HELLO BioPayload v2.0 (Nano ESP32)")
    t += timedelta(seconds=0.5)

    # Home
    tx("MOT_ENABLE")
    t += timedelta(milliseconds=30)
    rx("ACK MOT_ENABLE")
    t += timedelta(seconds=0.5)
    tx("MOT_HOME")
    t += timedelta(milliseconds=30)
    rx("ACK MOT_HOME")
    t += timedelta(seconds=18)
    rx("DONE MOT_HOME")
    t += timedelta(seconds=0.3)

    # SET_CONFIG
    cfg = (
        'SET_CONFIG {"run_id":"demo-001","priming":{"pump_ms":1000},'
        '"active":{"duration_ms":' + str(TOTAL_DURATION) + ','
        '"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":'
        + str(int(SCAN_INTERVAL * 1000)) + '}]},'
        '"scanning":{"homing":true,"settle_ms":200,"led_off_after_read":true,'
        '"wells":['
        '{"row":0,"col":0,"steps_from_home":14030,"led":[128,128,128]},'
        '{"row":0,"col":1,"steps_from_home":62563,"led":[128,128,128]},'
        '{"row":0,"col":2,"steps_from_home":109305,"led":[128,128,128]},'
        '{"row":0,"col":3,"steps_from_home":157301,"led":[128,128,128]}]}}'
    )
    tx(cfg)
    t += timedelta(milliseconds=60)
    rx("ACK SET_CONFIG")
    t += timedelta(seconds=0.5)

    # START
    tx("START")
    t += timedelta(milliseconds=30)
    rx("ACK START")
    rx("STATE PRIMING")
    t += timedelta(seconds=1.1)
    rx("STATE ACTIVE")

    total_wells = 0
    for scan_idx in range(N_SCANS):
        rx("STATE SCANNING")
        for well_idx in range(4):
            t += timedelta(seconds=4 + random.random() * 2)
            _, f590s, f630s, clrs = WELL_DATA[well_idx]
            rx(
                f'TELEM {{"event":"well","row":0,"col":{well_idx},'
                f'"f1":{random.randint(50,200)},'
                f'"f2":{random.randint(80,250)},'
                f'"f3":{random.randint(100,300)},'
                f'"f4":{random.randint(120,350)},'
                f'"f5":{random.randint(150,400)},'
                f'"f6":{f590s[scan_idx]},'
                f'"f7":{f630s[scan_idx]},'
                f'"f8":{random.randint(80,200)},'
                f'"clear":{clrs[scan_idx]},'
                f'"nir":{random.randint(30,120)}}}'
            )
            total_wells += 1
        t += timedelta(seconds=2)
        rx("STATE ACTIVE")
        if scan_idx < N_SCANS - 1:
            t += timedelta(seconds=SCAN_INTERVAL - 25)

    # DONE
    rx("STATE DONE")
    dur_ms = int(N_SCANS * SCAN_INTERVAL * 1000)
    rx(
        f'RESULT {{"run_id":"demo-001","status":"OK",'
        f'"scans":{N_SCANS},"wells":{total_wells},'
        f'"duration_ms":{dur_ms}}}'
    )
    rx("STATE IDLE")

    return lines


CONSOLE_LINES = generate_console_lines()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class DemoGUI:

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
        "c590":     "#ff6f00",
        "c630":     "#ce93d8",
        "cclr":     "#4dd0e1",
        "graph_bg": "#1a1a2e",
        "graph_gd": "#2a2a3e",
        "tab_active":   "#2d2d2d",
        "tab_inactive": "#1a1a1a",
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("BioPayload Command Center  [DEMO]")
        root.geometry("1360x940")
        root.minsize(1120, 780)
        root.configure(bg=self.C["bg"])

        self._current_well = 0
        self._hover_idx = None
        self._last_hover_ms = 0.0
        self._user_zoomed = False

        self._setup_styles()
        self._build_ui()
        self._populate_console()
        self._draw_well(0)

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

        left_outer = ttk.Frame(body, style="Dark.TFrame")
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_left_scroll(left_outer)

        right = ttk.Frame(body, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=5)
        right.rowconfigure(1, weight=0)
        right.rowconfigure(2, weight=2)
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

        tk.Label(hdr, text="DEMO MODE",
                 bg="#ff6f00", fg="white",
                 font=("Helvetica", 9, "bold"), padx=8, pady=2).pack(side=tk.RIGHT)

        tk.Button(
            hdr, text="■  ABORT",
            bg="#b71c1c", fg="white", activebackground="#d32f2f",
            font=("Helvetica", 12, "bold"),
            padx=16, pady=6, relief=tk.FLAT, cursor="hand2",
            state=tk.DISABLED).pack(side=tk.RIGHT, padx=(0, 8))

    # -------------------------------------------------------------------------
    # Left scrollable column (same panels as command_gui, all disabled)
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

    def _lpanel(self, parent, title):
        c = ttk.Frame(parent, style="Dark.TFrame")
        c.pack(fill=tk.X, pady=(0, 8))
        p = ttk.Frame(c, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.X)
        ttk.Label(p, text=title, style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))
        return p

    def _build_conn_panel(self, parent):
        p = self._lpanel(parent, "Connection")
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text="Port:", style="Dim.TLabel").pack(side=tk.LEFT)
        cb = ttk.Combobox(row, values=["/dev/cu.usbmodemE4B063AF458C2"],
                          state="readonly", width=18)
        cb.current(0)
        cb.pack(side=tk.LEFT, padx=(6, 4), fill=tk.X, expand=True)

        crow = ttk.Frame(p, style="Panel.TFrame")
        crow.pack(fill=tk.X)
        ttk.Button(crow, text="Connected", style="Connect.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(crow, text="●", bg=self.C["panel"],
                 fg=self.C["success"], font=("Helvetica", 14)).pack(side=tk.LEFT, padx=(8, 0))

        qrow = ttk.Frame(p, style="Panel.TFrame")
        qrow.pack(fill=tk.X, pady=(8, 0))
        for cmd in ("PING", "HELLO", "STATE", "SYS_STATUS"):
            ttk.Button(qrow, text=cmd, style="Small.TButton",
                       state=tk.DISABLED).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

    def _build_motor_panel(self, parent):
        p = self._lpanel(parent, "Motor (Linear Actuator)")
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row, text="Steps:", style="Dim.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row, width=8, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(row, text="MOT_MOVE", style="Small.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT)

        row2 = ttk.Frame(p, style="Panel.TFrame")
        row2.pack(fill=tk.X, pady=(0, 4))
        for lbl in ("▶ FWD", "◀ REV", "■ STOP"):
            ttk.Button(row2, text=lbl, style="Small.TButton",
                       state=tk.DISABLED).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        row3 = ttk.Frame(p, style="Panel.TFrame")
        row3.pack(fill=tk.X)
        for lbl in ("HOME", "ENABLE", "DISABLE"):
            ttk.Button(row3, text=lbl, style="Small.TButton",
                       state=tk.DISABLED).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    def _build_pump_panel(self, parent):
        p = self._lpanel(parent, "Peristaltic Pump")
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row, text="ms:", style="Dim.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row, width=8, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(row, text="PUMP_RUN", style="Small.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT)

        row2 = ttk.Frame(p, style="Panel.TFrame")
        row2.pack(fill=tk.X)
        for lbl in ("ON", "OFF", "STATUS"):
            ttk.Button(row2, text=lbl, style="Small.TButton",
                       state=tk.DISABLED).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    def _build_led_panel(self, parent):
        p = self._lpanel(parent, "RGB LED")
        preview_row = ttk.Frame(p, style="Panel.TFrame")
        preview_row.pack(fill=tk.X, pady=(0, 6))
        tk.Canvas(preview_row, width=44, height=44, bg="#808080",
                  highlightthickness=1,
                  highlightbackground=self.C["border"]).pack(side=tk.LEFT, padx=(0, 10))

        sliders = ttk.Frame(preview_row, style="Panel.TFrame")
        sliders.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for label, val, fg in [("R", 128, "#f44336"), ("G", 128, "#4caf50"), ("B", 128, "#42a5f5")]:
            r = ttk.Frame(sliders, style="Panel.TFrame")
            r.pack(fill=tk.X, pady=1)
            tk.Label(r, text=label, bg=self.C["panel"], fg=fg,
                     font=("Helvetica", 9, "bold"), width=2).pack(side=tk.LEFT)
            tk.Scale(r, from_=0, to=255, orient=tk.HORIZONTAL,
                     bg=self.C["panel"], fg=self.C["dim"],
                     troughcolor=self.C["accent"], highlightthickness=0,
                     length=130, state=tk.DISABLED).pack(side=tk.LEFT, fill=tk.X, expand=True)

        btns = ttk.Frame(p, style="Panel.TFrame")
        btns.pack(fill=tk.X)
        for lbl in ("LED_SET", "LED_OFF", "STATUS"):
            ttk.Button(btns, text=lbl, style="Small.TButton",
                       state=tk.DISABLED).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    def _build_limit_panel(self, parent):
        p = self._lpanel(parent, "Limit Switch")
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill=tk.X)
        ttk.Button(row, text="LIM_STATUS", style="Small.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT)
        tk.Label(row, text="OPEN", bg=self.C["panel"],
                 fg=self.C["dim"], font=("Consolas", 12, "bold")).pack(side=tk.LEFT, padx=(12, 0))

    def _build_spec_panel(self, parent):
        p = self._lpanel(parent, "Spectral Sensor (AS7341)")
        ttk.Button(p, text="SPEC_READ  (≈250 ms)", style="Primary.TButton",
                   state=tk.DISABLED).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(p, text="SPEC_STATUS", style="Small.TButton",
                   state=tk.DISABLED).pack(anchor=tk.W, pady=(6, 0))

    def _build_sd_panel(self, parent):
        p = self._lpanel(parent, "SD Card")
        ttk.Button(p, text="SD_STATUS", style="Small.TButton",
                   state=tk.DISABLED).pack(anchor=tk.W)

    # -------------------------------------------------------------------------
    # Right panel: Graph with well tabs
    # -------------------------------------------------------------------------

    def _build_graph_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        p = ttk.Frame(container, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.BOTH, expand=True)

        ttk.Label(p, text="Well Readings — 590 nm, 630 nm & Clear",
                  style="Title.TLabel").pack(anchor=tk.W, pady=(0, 6))

        # Well tabs
        tab_row = ttk.Frame(p, style="Panel.TFrame")
        tab_row.pack(fill=tk.X, pady=(0, 2))

        self._tab_btns: list[tk.Button] = []
        for i in range(4):
            btn = tk.Button(
                tab_row, text=f"Well {i+1}",
                bg=self.C["tab_inactive"], fg=self.C["dim"],
                activebackground=self.C["tab_active"],
                activeforeground=self.C["text"],
                font=("Helvetica", 10, "bold"),
                bd=0, padx=16, pady=6, cursor="hand2",
                command=lambda idx=i: self._select_well(idx))
            btn.pack(side=tk.LEFT, padx=(0, 2))
            self._tab_btns.append(btn)

        # Value labels
        toolbar = ttk.Frame(p, style="Panel.TFrame")
        toolbar.pack(fill=tk.X, pady=(4, 4))

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

        self._lbl_n = tk.Label(toolbar, text=f"n={N_SCANS}",
                               bg=self.C["panel"], fg=self.C["dim"],
                               font=("Consolas", 10))
        self._lbl_n.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="Reset View", style="Small.TButton",
                   command=self._reset_graph_view).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Zoom Out", style="Small.TButton",
                   command=lambda: self._zoom_graph(1.4)).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Zoom In", style="Small.TButton",
                   command=lambda: self._zoom_graph(0.7)).pack(side=tk.RIGHT, padx=(4, 0))

        self._fig = Figure(figsize=(5, 3), dpi=100, facecolor=self.C["graph_bg"])
        self._ax  = self._fig.add_subplot(111)
        self._style_ax()
        self._fig_canvas = FigureCanvasTkAgg(self._fig, master=p)
        self._fig_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
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

    def _select_well(self, idx: int):
        self._current_well = idx
        self._hover_idx = None
        self._user_zoomed = False
        self._draw_well(idx)

    def _draw_well(self, idx: int):
        for i, btn in enumerate(self._tab_btns):
            if i == idx:
                btn.configure(bg=self.C["tab_active"], fg=self.C["text"])
            else:
                btn.configure(bg=self.C["tab_inactive"], fg=self.C["dim"])

        ts, f590, f630, clr = WELL_DATA[idx]
        self._cur_ts   = ts
        self._cur_f590 = f590
        self._cur_f630 = f630
        self._cur_clr  = clr

        self._lbl590.configure(text=f"590 nm: {f590[-1]}")
        self._lbl630.configure(text=f"630 nm: {f630[-1]}")
        self._lblclr.configure(text=f"Clear: {clr[-1]}")
        self._redraw_graph()

    def _redraw_graph(self):
        ax, C = self._ax, self.C
        saved_xlim = ax.get_xlim() if self._user_zoomed else None
        saved_ylim = ax.get_ylim() if self._user_zoomed else None

        ax.cla()
        self._style_ax()

        ts   = self._cur_ts
        f590 = self._cur_f590
        f630 = self._cur_f630
        clr  = self._cur_clr

        ax.plot(ts, f590, color=C["c590"], linewidth=1.6, label="590 nm",
                marker="o", markersize=3)
        ax.fill_between(ts, f590, color=C["c590"], alpha=0.08)
        ax.plot(ts, f630, color=C["c630"], linewidth=1.6, label="630 nm",
                marker="s", markersize=3)
        ax.fill_between(ts, f630, color=C["c630"], alpha=0.08)
        ax.plot(ts, clr,  color=C["cclr"], linewidth=1.2, label="Clear",
                linestyle="--", marker="^", markersize=3)

        ax.legend(fontsize=8, facecolor=C["graph_bg"],
                  labelcolor=C["dim"], framealpha=0.7)

        well_label = f"Well {self._current_well + 1}  (pos {WELL_POSITIONS[self._current_well]:,} steps)"
        ax.set_title(well_label, color=C["text"], fontsize=10, pad=8)

        if not self._user_zoomed:
            all_v = list(f590) + list(f630) + list(clr)
            lo = max(0, min(all_v) - 80)
            hi = max(all_v) + 80
            ax.set_ylim(lo, hi)

        # Hover annotation
        idx = self._hover_idx
        if idx is not None and 0 <= idx < len(ts):
            hx, hy59, hy63, hycl = ts[idx], f590[idx], f630[idx], clr[idx]
            ax.axvline(hx, color=C["dim"], linewidth=0.8, linestyle="--", alpha=0.6)
            ax.plot(hx, hy59, "o", color=C["c590"], markersize=7, zorder=5)
            ax.plot(hx, hy63, "o", color=C["c630"], markersize=7, zorder=5)
            ax.plot(hx, hycl, "o", color=C["cclr"],  markersize=7, zorder=5)

            ax_w = ax.get_xlim()[1] - ax.get_xlim()[0] or 1
            x_frac = (hx - ax.get_xlim()[0]) / ax_w
            x_offset = -130 if x_frac > 0.75 else 14
            y_anchor = max(hy59, hy63, hycl)
            ax.annotate(
                f"scan #{idx+1}  t={hx:.0f}s\n590 = {hy59}\n630 = {hy63}\nclr = {hycl}",
                xy=(hx, y_anchor),
                xytext=(x_offset, 10),
                textcoords="offset points",
                color=C["text"], fontsize=8,
                bbox=dict(boxstyle="round,pad=0.4",
                          facecolor=C["panel"],
                          edgecolor=C["border"],
                          alpha=0.92),
                arrowprops=dict(arrowstyle="->", color=C["dim"], lw=0.8),
                zorder=10)

        if self._user_zoomed and saved_xlim and saved_ylim:
            ax.set_xlim(saved_xlim)
            ax.set_ylim(saved_ylim)

        self._fig.tight_layout(pad=0.8)
        self._fig_canvas.draw_idle()

    def _zoom_graph(self, factor):
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        if x0 == x1 or y0 == y1:
            return
        cx, cy = (x0+x1)/2, (y0+y1)/2
        hw, hh = (x1-x0)*factor/2, (y1-y0)*factor/2
        self._ax.set_xlim(cx-hw, cx+hw)
        self._ax.set_ylim(cy-hh, cy+hh)
        self._user_zoomed = True
        self._fig_canvas.draw_idle()

    def _reset_graph_view(self):
        self._user_zoomed = False
        self._redraw_graph()

    def _on_hover(self, event):
        if not event.inaxes or not self._cur_ts:
            if self._hover_idx is not None:
                self._hover_idx = None
                self._redraw_graph()
            return

        xs = self._cur_ts
        new_idx = min(range(len(xs)), key=lambda i: abs(xs[i] - event.xdata))
        if new_idx == self._hover_idx:
            return
        self._hover_idx = new_idx

        now_ms = time.time() * 1000
        if now_ms - self._last_hover_ms < 33:
            return
        self._last_hover_ms = now_ms
        self._redraw_graph()

    # -------------------------------------------------------------------------
    # Right panel: Status
    # -------------------------------------------------------------------------

    def _build_status_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self._status_visible = True
        self._status_toggle_btn = tk.Button(
            container, text="▼ System Status",
            bg=self.C["accent"], fg=self.C["dim"], bd=0,
            activebackground=self.C["border"], activeforeground=self.C["text"],
            font=("Consolas", 10), anchor=tk.W, padx=6, pady=2,
            command=self._toggle_status_panel)
        self._status_toggle_btn.pack(fill=tk.X)

        self._status_body = ttk.Frame(container, style="Panel.TFrame", padding=(10, 6))
        self._status_body.pack(fill=tk.X)

        status_text = "state:IDLE  pos:0  pump:OFF  motor:IDLE  led:OFF  limit:OPEN  spec:OK  sd:OK"
        self._status_text_lbl = tk.Label(
            self._status_body, text=status_text,
            bg=self.C["panel"], fg=self.C["dim"],
            font=("Consolas", 10), anchor=tk.W, justify=tk.LEFT)
        self._status_text_lbl.pack(fill=tk.X)

    def _toggle_status_panel(self):
        if self._status_visible:
            self._status_body.pack_forget()
            self._status_toggle_btn.configure(text="▶ System Status")
            self._status_visible = False
        else:
            self._status_body.pack(fill=tk.X)
            self._status_toggle_btn.configure(text="▼ System Status")
            self._status_visible = True

    # -------------------------------------------------------------------------
    # Right panel: Console
    # -------------------------------------------------------------------------

    def _build_console_panel(self, parent):
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.grid(row=2, column=0, sticky="nsew")
        p = ttk.Frame(container, style="Panel.TFrame", padding=10)
        p.pack(fill=tk.BOTH, expand=True)

        ttk.Label(p, text="Serial Console", style="Title.TLabel").pack(
            anchor=tk.W, pady=(0, 6))

        tx_row = ttk.Frame(p, style="Panel.TFrame")
        tx_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(tx_row, text="TX:", style="Dim.TLabel").pack(side=tk.LEFT)
        ttk.Entry(tx_row, font=("Consolas", 10),
                  state=tk.DISABLED).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))
        ttk.Button(tx_row, text="Send", style="Small.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT)
        ttk.Button(tx_row, text="Clear", style="Small.TButton",
                   state=tk.DISABLED).pack(side=tk.LEFT, padx=(4, 0))

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

    def _populate_console(self):
        self._console.configure(state=tk.NORMAL)
        for tag, text in CONSOLE_LINES:
            self._console.insert(tk.END, text + "\n", tag)
        self._console.see(tk.END)
        self._console.configure(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    DemoGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
