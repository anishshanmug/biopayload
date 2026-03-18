#!/usr/bin/env python3
"""
Well-Plate Scan GUI

Tkinter frontend for the well-plate scan demo firmware (main_component_dev.cpp).
Connects to the Arduino Nano ESP32 over serial, starts a 54.9 s stepper scan,
plots 590 nm readings in real time, shows the top-4 peaks the firmware detected,
and saves all readings + peaks to CSV.

Usage:
    python wellplate_gui.py
"""

import csv
import os
import re
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import serial
import serial.tools.list_ports

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ============================================================================
# Serial helpers
# ============================================================================

def get_serial_ports() -> list[str]:
    ports = []
    for p in serial.tools.list_ports.comports():
        if "Bluetooth" not in p.description and "debug" not in p.device:
            ports.append(p.device)
    return sorted(ports)


class BoardSerial:
    """Background-reader serial wrapper."""

    def __init__(self, on_line, baudrate: int = 115200):
        self.on_line = on_line
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
            self._ser.write((cmd if cmd.endswith("\n") else cmd + "\n").encode())
        except serial.SerialException:
            pass

    def _read_loop(self):
        buf = ""
        while self._running and self._ser and self._ser.is_open:
            try:
                if self._ser.in_waiting:
                    data = self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            self.on_line(line)
                else:
                    time.sleep(0.01)
            except serial.SerialException:
                break


# ============================================================================
# Line parsers
# ============================================================================

_SCAN_SPEC_RE = re.compile(
    r"SCAN\s+T:(\d+)\s+"
    r"415nm:(\d+)\s+445nm:(\d+)\s+480nm:(\d+)\s+515nm:(\d+)\s+"
    r"555nm:(\d+)\s+590nm:(\d+)\s+630nm:(\d+)\s+680nm:(\d+)\s+"
    r"Clear:(\d+)\s+NIR:(\d+)"
)

_PLAIN_SPEC_RE = re.compile(
    r"415nm:(\d+)\s+445nm:(\d+)\s+480nm:(\d+)\s+515nm:(\d+)\s+"
    r"555nm:(\d+)\s+590nm:(\d+)\s+630nm:(\d+)\s+680nm:(\d+)\s+"
    r"Clear:(\d+)\s+NIR:(\d+)"
)

_WELL_RE = re.compile(r"WELL\s+(\d+)\s+590nm=(\d+)\s+n=(\d+)")


def parse_scan_spectral(line: str) -> Optional[dict]:
    m = _SCAN_SPEC_RE.search(line)
    if not m:
        return None
    keys = ["t_ms", "415nm", "445nm", "480nm", "515nm",
            "555nm", "590nm", "630nm", "680nm", "clear", "nir"]
    return {k: int(v) for k, v in zip(keys, m.groups())}


def parse_plain_spectral(line: str) -> Optional[dict]:
    if line.startswith("SCAN"):
        return None
    m = _PLAIN_SPEC_RE.search(line)
    if not m:
        return None
    keys = ["415nm", "445nm", "480nm", "515nm",
            "555nm", "590nm", "630nm", "680nm", "clear", "nir"]
    return {k: int(v) for k, v in zip(keys, m.groups())}


def parse_well(line: str) -> Optional[dict]:
    m = _WELL_RE.search(line)
    if not m:
        return None
    return {"well": int(m.group(1)), "avg": int(m.group(2)), "n": int(m.group(3))}


# ============================================================================
# Application
# ============================================================================

SCAN_DURATION_S = 39.0


class WellPlateApp:

    COLORS = {
        "bg":       "#121212",
        "panel":    "#1e1e1e",
        "accent":   "#2d2d2d",
        "primary":  "#e0e0e0",
        "success":  "#4caf50",
        "warning":  "#ff9800",
        "error":    "#f44336",
        "text":     "#e0e0e0",
        "text_dim": "#888888",
        "graph_bg": "#1a1a2e",
        "graph_ln": "#ff6f00",
        "graph_gd": "#333333",
        "well_clr": "#ffab00",
    }

    MAX_GRAPH_PTS = 600

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Well-Plate Scan")
        self.root.geometry("1060x820")
        self.root.minsize(940, 720)
        self.root.configure(bg=self.COLORS["bg"])

        self.board = BoardSerial(self._on_serial_line)

        # Scan data
        self._scan_times: deque[float] = deque(maxlen=self.MAX_GRAPH_PTS)
        self._scan_590: deque[int] = deque(maxlen=self.MAX_GRAPH_PTS)
        self._all_readings: list[dict] = []
        self._wells: list[dict] = []
        self._scanning = False
        self._resetting = False

        # Experiment metadata
        self._experiment_name = ""

        self._setup_styles()
        self._build_ui()
        self._log("Application started", "info")

    # ------------------------------------------------------------------ styles
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Panel.TFrame", background=self.COLORS["panel"])
        style.configure("Dark.TFrame",  background=self.COLORS["bg"])
        style.configure("Title.TLabel",
                        background=self.COLORS["panel"],
                        foreground=self.COLORS["text"],
                        font=("Helvetica", 11, "bold"))
        style.configure("Value.TLabel",
                        background=self.COLORS["panel"],
                        foreground=self.COLORS["text"],
                        font=("Helvetica", 12))
        style.configure("Dim.TLabel",
                        background=self.COLORS["panel"],
                        foreground=self.COLORS["text_dim"],
                        font=("Helvetica", 10))
        style.configure("Header.TLabel",
                        background=self.COLORS["bg"],
                        foreground=self.COLORS["text"],
                        font=("Helvetica", 18, "bold"))
        style.configure("Primary.TButton", font=("Helvetica", 10, "bold"), padding=(15, 8))
        style.configure("Connect.TButton", font=("Helvetica", 10), padding=(10, 5))
        style.configure("Well.TLabel",
                        background=self.COLORS["panel"],
                        foreground=self.COLORS["well_clr"],
                        font=("Consolas", 12, "bold"))

    # ---------------------------------------------------------------- layout
    def _build_ui(self):
        main = ttk.Frame(self.root, style="Dark.TFrame", padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_header(main)

        body = ttk.Frame(main, style="Dark.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Dark.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._build_connection_panel(left)
        self._build_stepper_panel(left)
        self._build_pump_panel(left)
        self._build_scan_panel(left)
        self._build_peaks_panel(left)
        self._build_save_panel(left)

        right = ttk.Frame(body, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=1)

        self._build_graph_panel(right)
        self._build_log_panel(right)

    # ---------------------------------------------------------------- header
    def _build_header(self, parent):
        hdr = ttk.Frame(parent, style="Dark.TFrame")
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Well-Plate Scan Station", style="Header.TLabel").pack(side=tk.LEFT)
        tk.Label(hdr, text="demo v0.1", bg=self.COLORS["accent"],
                 fg=self.COLORS["text_dim"], font=("Helvetica", 9),
                 padx=8, pady=2).pack(side=tk.RIGHT)

    # ---------------------------------------------------------------- connection
    def _build_connection_panel(self, parent):
        panel = self._panel(parent, "Connection")

        row = ttk.Frame(panel, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(row, text="Port:", style="Dim.TLabel").pack(side=tk.LEFT)

        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(row, textvariable=self._port_var,
                                        state="readonly", width=20)
        self._port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        ttk.Button(row, text="⟳", width=3,
                   command=self._refresh_ports).pack(side=tk.LEFT, padx=4)

        self._conn_btn = ttk.Button(row, text="Connect", style="Connect.TButton",
                                    command=self._toggle_conn)
        self._conn_btn.pack(side=tk.LEFT)

        self._conn_dot = tk.Label(row, text="●", bg=self.COLORS["panel"],
                                  fg=self.COLORS["error"], font=("Helvetica", 12))
        self._conn_dot.pack(side=tk.LEFT, padx=(6, 0))

        self._refresh_ports()

    def _refresh_ports(self):
        ports = get_serial_ports()
        self._port_combo["values"] = ports if ports else ["No ports"]
        self._port_var.set(ports[0] if ports else "No ports")

    def _toggle_conn(self):
        if self.board.connected:
            self.board.disconnect()
            self._conn_btn.configure(text="Connect")
            self._conn_dot.configure(fg=self.COLORS["error"])
            self._log("Disconnected", "info")
        else:
            port = self._port_var.get()
            if not port or port == "No ports":
                messagebox.showerror("Error", "No port selected")
                return
            self._log(f"Connecting to {port}…", "info")
            if self.board.connect(port):
                self._conn_btn.configure(text="Disconnect")
                self._conn_dot.configure(fg=self.COLORS["success"])
                self._log("Connected", "success")
            else:
                self._log("Connection failed", "error")

    # ---------------------------------------------------------------- stepper controls
    def _build_stepper_panel(self, parent):
        panel = self._panel(parent, "Stepper Control")

        btn_frame = ttk.Frame(panel, style="Panel.TFrame")
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        self._stepper_fwd_btn = ttk.Button(
            btn_frame, text="▶ Forward", style="Primary.TButton",
            command=lambda: self._stepper_cmd("p", "forward"))
        self._stepper_fwd_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self._stepper_rev_btn = ttk.Button(
            btn_frame, text="◀ Reverse", style="Primary.TButton",
            command=lambda: self._stepper_cmd("r", "reverse"))
        self._stepper_rev_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 4))

        self._stepper_stop_btn = ttk.Button(
            btn_frame, text="■ Stop", command=lambda: self._stepper_cmd("x", "stop"))
        self._stepper_stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        self._reset_btn = ttk.Button(
            panel, text="↺  Reset Stage (39 s reverse)",
            style="Primary.TButton", command=self._reset_stage)
        self._reset_btn.pack(fill=tk.X)

    def _stepper_cmd(self, cmd: str, label: str):
        if not self.board.connected:
            messagebox.showwarning("Not connected", "Connect to board first")
            return
        if self._resetting:
            self._cancel_reset()
        if self._scanning:
            self._scanning = False
            self._scan_btn.configure(text="▶  Start Scan", state=tk.NORMAL)
            self._status_label.configure(text="ABORTED", fg=self.COLORS["error"])
            self._log("Scan aborted by stepper override", "warning")
        self.board.send(cmd)
        self._log(f"Stepper: {label}", "info")

    def _reset_stage(self):
        if not self.board.connected:
            messagebox.showwarning("Not connected", "Connect to board first")
            return
        if self._scanning:
            messagebox.showwarning("Scan active", "Stop the scan before resetting")
            return
        if self._resetting:
            return

        self._resetting = True
        self._reset_btn.configure(text="Resetting…", state=tk.DISABLED)
        self._reset_start = time.time()

        self.board.send("r")
        self.root.after(100, lambda: self.board.send("p"))
        self._reset_after_id = self.root.after(39100, self._finish_reset)
        self._log("Stage reset started (39 s reverse)", "info")
        self._tick_reset()

    def _tick_reset(self):
        if not self._resetting:
            return
        elapsed = time.time() - self._reset_start
        remaining = max(0, SCAN_DURATION_S - elapsed)
        self._reset_btn.configure(text=f"Resetting… {remaining:.0f} s")
        if self._resetting:
            self.root.after(500, self._tick_reset)

    def _finish_reset(self):
        self.board.send("x")
        self.root.after(100, lambda: self.board.send("r"))
        self._resetting = False
        self._reset_btn.configure(text="↺  Reset Stage (39 s reverse)", state=tk.NORMAL)
        self._log("Stage reset complete", "success")

    def _cancel_reset(self):
        self._resetting = False
        if hasattr(self, "_reset_after_id") and self._reset_after_id:
            self.root.after_cancel(self._reset_after_id)
            self._reset_after_id = None
        self._reset_btn.configure(text="↺  Reset Stage (39 s reverse)", state=tk.NORMAL)
        self._log("Stage reset cancelled", "warning")

    # ---------------------------------------------------------------- pump controls
    def _build_pump_panel(self, parent):
        panel = self._panel(parent, "Pump")

        self._pump_on = False
        self._pump_btn = ttk.Button(
            panel, text="Toggle Pump", style="Primary.TButton",
            command=self._toggle_pump)
        self._pump_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self._pump_status = tk.Label(
            panel, text="OFF", bg=self.COLORS["panel"],
            fg=self.COLORS["text_dim"], font=("Helvetica", 12, "bold"))
        self._pump_status.pack(side=tk.LEFT, padx=(12, 0))

    def _toggle_pump(self):
        if not self.board.connected:
            messagebox.showwarning("Not connected", "Connect to board first")
            return
        self.board.send("m")

    # ---------------------------------------------------------------- scan controls
    def _build_scan_panel(self, parent):
        panel = self._panel(parent, "Scan Control")

        name_row = ttk.Frame(panel, style="Panel.TFrame")
        name_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_row, text="Name:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._name_var = tk.StringVar(value=datetime.now().strftime("scan_%Y%m%d_%H%M%S"))
        ttk.Entry(name_row, textvariable=self._name_var, width=22,
                  font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)

        self._scan_btn = ttk.Button(panel, text="▶  Start Scan",
                                    style="Primary.TButton",
                                    command=self._start_scan)
        self._scan_btn.pack(fill=tk.X, pady=(0, 6))

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(panel, variable=self._progress_var,
                                             maximum=SCAN_DURATION_S, length=200)
        self._progress_bar.pack(fill=tk.X)

        self._elapsed_label = tk.Label(panel, text="Elapsed: -- / 39.0 s",
                                       bg=self.COLORS["panel"],
                                       fg=self.COLORS["text_dim"],
                                       font=("Consolas", 10))
        self._elapsed_label.pack(anchor=tk.W, pady=(4, 0))

        self._status_label = tk.Label(panel, text="IDLE",
                                      bg=self.COLORS["panel"],
                                      fg=self.COLORS["text_dim"],
                                      font=("Helvetica", 14, "bold"))
        self._status_label.pack(anchor=tk.W, pady=(4, 0))

    def _start_scan(self):
        if not self.board.connected:
            messagebox.showwarning("Not connected", "Connect to board first")
            return
        if self._scanning:
            return

        self._scan_times.clear()
        self._scan_590.clear()
        self._all_readings.clear()
        self._wells.clear()
        self._clear_well_labels()
        self._redraw_graph()

        self._experiment_name = self._name_var.get() or "untitled"
        self._scanning = True
        self._scan_gui_start = time.time()
        self._scan_btn.configure(text="Scanning…", state=tk.DISABLED)
        self._status_label.configure(text="SCANNING", fg=self.COLORS["warning"])

        self.board.send("s")
        self._log(f"Scan started: {self._experiment_name}", "info")
        self._tick_progress()

    def _tick_progress(self):
        if not self._scanning:
            return
        elapsed = time.time() - self._scan_gui_start
        self._progress_var.set(min(elapsed, SCAN_DURATION_S))
        self._elapsed_label.configure(text=f"Elapsed: {elapsed:.1f} / {SCAN_DURATION_S} s")
        if elapsed >= SCAN_DURATION_S + 2.0:
            self._finish_scan()
            self._redraw_graph()
            return
        self.root.after(200, self._tick_progress)

    def _finish_scan(self):
        self._scanning = False
        self._progress_var.set(SCAN_DURATION_S)
        self._elapsed_label.configure(text=f"Elapsed: {SCAN_DURATION_S} / {SCAN_DURATION_S} s")
        self._scan_btn.configure(text="▶  Start Scan", state=tk.NORMAL)
        self._status_label.configure(text="COMPLETE", fg=self.COLORS["success"])
        self._name_var.set(datetime.now().strftime("scan_%Y%m%d_%H%M%S"))
        self._log("Scan complete", "success")

    # ---------------------------------------------------------------- wells panel
    def _build_peaks_panel(self, parent):
        panel = self._panel(parent, "Well Averages (590 nm)")

        self._well_labels: list[tk.Label] = []
        for i in range(4):
            lbl = tk.Label(panel,
                           text=f"Well {i+1}:  --",
                           bg=self.COLORS["panel"],
                           fg=self.COLORS["well_clr"],
                           font=("Consolas", 11),
                           anchor=tk.W)
            lbl.pack(fill=tk.X, pady=1)
            self._well_labels.append(lbl)

    def _clear_well_labels(self):
        for i, lbl in enumerate(self._well_labels):
            lbl.configure(text=f"Well {i+1}:  --")

    def _update_well_label(self, well: dict):
        idx = well["well"] - 1
        if 0 <= idx < len(self._well_labels):
            self._well_labels[idx].configure(
                text=f"Well {well['well']}:  avg {well['avg']}  ({well['n']} samples)"
            )

    # ---------------------------------------------------------------- save panel
    def _build_save_panel(self, parent):
        panel = self._panel(parent, "Export")

        self._save_btn = ttk.Button(panel, text="Save Results to CSV",
                                    style="Primary.TButton",
                                    command=self._save_csv)
        self._save_btn.pack(fill=tk.X)

    def _save_csv(self):
        if not self._all_readings and not self._wells:
            messagebox.showinfo("Nothing to save", "Run a scan first")
            return

        default_name = f"{self._experiment_name}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=default_name,
            initialdir=os.path.dirname(os.path.abspath(__file__)),
        )
        if not path:
            return

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)

            writer.writerow(["Experiment", self._experiment_name])
            writer.writerow(["Date", datetime.now().isoformat()])
            writer.writerow([])

            if self._wells:
                writer.writerow(["=== Well Averages (590 nm) ==="])
                writer.writerow(["Well", "590nm Avg", "Samples"])
                for w in sorted(self._wells, key=lambda x: x["well"]):
                    writer.writerow([w["well"], w["avg"], w["n"]])
                writer.writerow([])

            if self._all_readings:
                writer.writerow(["=== All Scan Readings ==="])
                cols = ["t_ms", "415nm", "445nm", "480nm", "515nm",
                        "555nm", "590nm", "630nm", "680nm", "clear", "nir"]
                writer.writerow(cols)
                for r in self._all_readings:
                    writer.writerow([r.get(c, "") for c in cols])

        self._log(f"Saved to {os.path.basename(path)}", "success")

    # ---------------------------------------------------------------- graph
    def _build_graph_panel(self, parent):
        panel = self._panel(parent, "590 nm — Live Scan", expand=True)

        toolbar = ttk.Frame(panel, style="Panel.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 6))

        self._latest_590_label = tk.Label(
            toolbar, text="590 nm: --", bg=self.COLORS["panel"],
            fg=self.COLORS["graph_ln"], font=("Consolas", 13, "bold"))
        self._latest_590_label.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="Clear Graph",
                   command=self._clear_graph).pack(side=tk.RIGHT)

        self._fig = Figure(figsize=(6, 3), dpi=100, facecolor=self.COLORS["graph_bg"])
        self._ax = self._fig.add_subplot(111)
        self._style_axes()
        self._canvas = FigureCanvasTkAgg(self._fig, master=panel)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _style_axes(self):
        ax = self._ax
        ax.set_facecolor(self.COLORS["graph_bg"])
        ax.tick_params(colors=self.COLORS["text_dim"], labelsize=8)
        ax.set_xlabel("Time (s)", color=self.COLORS["text_dim"], fontsize=9)
        ax.set_ylabel("590 nm", color=self.COLORS["text_dim"], fontsize=9)
        for spine in ax.spines.values():
            spine.set_color(self.COLORS["graph_gd"])
        ax.grid(True, color=self.COLORS["graph_gd"], linewidth=0.4, alpha=0.6)

    def _push_590(self, t_s: float, value: int):
        self._scan_times.append(t_s)
        self._scan_590.append(value)
        self._redraw_graph()
        self._latest_590_label.configure(text=f"590 nm: {value}")

    def _redraw_graph(self):
        ax = self._ax
        ax.cla()
        self._style_axes()
        if self._scan_times:
            xs = list(self._scan_times)
            ys = list(self._scan_590)
            ax.plot(xs, ys, color=self.COLORS["graph_ln"], linewidth=1.4)
            ax.fill_between(xs, ys, color=self.COLORS["graph_ln"], alpha=0.10)
            ax.set_xlim(0, max(SCAN_DURATION_S, max(xs) + 1))
            lo = max(0, min(ys) - 100)
            hi = max(ys) + 100
            if lo == hi:
                lo -= 50
                hi += 50
            ax.set_ylim(lo, hi)

            # Shade well time windows and label averages
            well_windows = [(8, 9), (17.5, 18.5), (27, 28), (36.5, 37.5)]
            for i, (ws, we) in enumerate(well_windows):
                ax.axvspan(ws, we, color=self.COLORS["well_clr"],
                           alpha=0.15, zorder=0)
            for w in self._wells:
                mid = {1: 8.5, 2: 18.0, 3: 27.5, 4: 37.0}.get(w["well"], 0)
                ax.annotate(f"W{w['well']}={w['avg']}", xy=(mid, w["avg"]),
                            xytext=(0, 12), textcoords="offset points",
                            color=self.COLORS["well_clr"],
                            fontsize=8, fontweight="bold", ha="center")
                ax.plot(mid, w["avg"], marker="D", color=self.COLORS["well_clr"],
                        markersize=6, zorder=5)

        self._fig.tight_layout(pad=1.0)
        self._canvas.draw_idle()

    def _clear_graph(self):
        self._scan_times.clear()
        self._scan_590.clear()
        self._redraw_graph()
        self._latest_590_label.configure(text="590 nm: --")

    # ---------------------------------------------------------------- log
    def _build_log_panel(self, parent):
        panel = self._panel(parent, "Event Log", expand=True)

        self._log_text = tk.Text(panel, height=6, bg=self.COLORS["bg"],
                                 fg=self.COLORS["text_dim"],
                                 font=("Consolas", 9), state=tk.DISABLED)
        self._log_text.pack(fill=tk.BOTH, expand=True)

        for tag, color in [
            ("info",    self.COLORS["text"]),
            ("success", self.COLORS["success"]),
            ("warning", self.COLORS["warning"]),
            ("error",   self.COLORS["error"]),
            ("rx",      "#c3e88d"),
        ]:
            self._log_text.tag_configure(tag, foreground=color)

    def _log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] {msg}\n", level)
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    # ---------------------------------------------------------------- helpers
    def _panel(self, parent, title: str, expand=False) -> ttk.Frame:
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=expand, pady=(0, 10))
        p = ttk.Frame(container, style="Panel.TFrame", padding=12)
        p.pack(fill=tk.BOTH, expand=True)
        ttk.Label(p, text=title, style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))
        return p

    # ---------------------------------------------------------------- serial dispatch
    def _on_serial_line(self, line: str):
        self.root.after(0, lambda: self._dispatch(line))

    def _dispatch(self, line: str):
        # Scan data line
        scan = parse_scan_spectral(line)
        if scan is not None:
            t_s = scan["t_ms"] / 1000.0
            self._push_590(t_s, scan["590nm"])
            self._all_readings.append(scan)
            return

        # Plain spectral (idle readings)
        plain = parse_plain_spectral(line)
        if plain is not None:
            return

        # Well result
        well = parse_well(line)
        if well is not None:
            self._wells.append(well)
            self._update_well_label(well)
            self._log(f"Well {well['well']}: avg 590nm={well['avg']}  ({well['n']} samples)", "success")
            return

        if line == "SCAN_START":
            self._log("Board acknowledged scan start", "info")
        elif line == "SCAN_DONE":
            self._finish_scan()
            self._redraw_graph()
        elif line == "SCAN_ABORTED":
            if self._scanning:
                self._scanning = False
                self._scan_btn.configure(text="▶  Start Scan", state=tk.NORMAL)
                self._status_label.configure(text="ABORTED", fg=self.COLORS["error"])
            self._log("Scan aborted", "warning")
        elif line == "STOPPED":
            self._log("Stepper stopped", "info")
        elif line == "PUMP_ON":
            self._pump_on = True
            self._pump_status.configure(text="ON", fg=self.COLORS["success"])
            self._log("Pump ON", "success")
        elif line == "PUMP_OFF":
            self._pump_on = False
            self._pump_status.configure(text="OFF", fg=self.COLORS["text_dim"])
            self._log("Pump OFF", "info")
        elif line.startswith("SD_OK"):
            self._log(f"Saved to SD: {line[6:]}", "success")
        elif line.startswith("SD_ERR"):
            self._log(f"SD error: {line[7:]}", "error")
        elif line.startswith("DIR:") or line in ("PAUSED", "RUNNING"):
            self._log(line, "info")
        elif line.startswith("SD OK") or line.startswith("SD FAIL"):
            self._log(line, "info" if "OK" in line else "warning")
        elif line.startswith("ERR") or line.startswith("AS7341 FAIL"):
            self._log(line, "error")


# ============================================================================
# Entry point
# ============================================================================

def main():
    root = tk.Tk()
    app = WellPlateApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: _on_close(app, root))
    root.mainloop()


def _on_close(app: WellPlateApp, root: tk.Tk):
    app.board.disconnect()
    root.destroy()


if __name__ == "__main__":
    main()
