#!/usr/bin/env python3
"""
BioPayload Component Dev GUI

Tkinter control panel for the two-board component-dev setup:
  - Nano  : peristaltic pump + AS7341 spectral sensor + pot-controlled RGB LED
  - Uno   : linear actuator (stepper via TMC2208)

Talks to the existing nano_component_dev / uno_component_dev firmwares
over serial (115200 baud).  No firmware changes required.

Usage:
    python component_dev_gui.py
"""

import re
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox, ttk
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
    """Thin wrapper around pyserial with a background reader thread."""

    def __init__(self, name: str, on_line, on_raw=None, baudrate: int = 115200):
        self.name = name
        self.on_line = on_line      # callback(board_name, line)
        self.on_raw = on_raw        # callback(board_name, direction, text)
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
            time.sleep(2)  # wait for Arduino reset
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            return True
        except serial.SerialException as exc:
            self.on_line(self.name, f"ERR serial: {exc}")
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
        if self.on_raw:
            self.on_raw(self.name, "TX", cmd.strip())
        try:
            self._ser.write((cmd if cmd.endswith("\n") else cmd + "\n").encode())
        except serial.SerialException as exc:
            self.on_line(self.name, f"ERR serial write: {exc}")

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
                            if self.on_raw:
                                self.on_raw(self.name, "RX", line)
                            self.on_line(self.name, line)
                else:
                    time.sleep(0.01)
            except serial.SerialException:
                break


# ============================================================================
# Spectral-line parser
# ============================================================================

_SPEC_RE = re.compile(
    r"415nm:(\d+)\s+445nm:(\d+)\s+480nm:(\d+)\s+515nm:(\d+)\s+"
    r"555nm:(\d+)\s+590nm:(\d+)\s+630nm:(\d+)\s+680nm:(\d+)\s+"
    r"Clear:(\d+)\s+NIR:(\d+)"
)

_LED_RE = re.compile(
    r"LED\s+Pot:(\d+)\s+Hue:([\d.]+)\s+RGB:(\d+),(\d+),(\d+)"
)


def parse_spectral(line: str) -> Optional[dict]:
    m = _SPEC_RE.search(line)
    if not m:
        return None
    keys = [
        "415nm", "445nm", "480nm", "515nm",
        "555nm", "590nm", "630nm", "680nm",
        "clear", "nir",
    ]
    return {k: int(v) for k, v in zip(keys, m.groups())}


def parse_led(line: str) -> Optional[dict]:
    m = _LED_RE.search(line)
    if not m:
        return None
    return {
        "pot": int(m.group(1)),
        "hue": float(m.group(2)),
        "r": int(m.group(3)),
        "g": int(m.group(4)),
        "b": int(m.group(5)),
    }


# ============================================================================
# Application
# ============================================================================

class ComponentDevApp:

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
        "idle":     "#666666",
        "running":  "#4caf50",
        "graph_bg": "#1a1a2e",
        "graph_ln": "#00e5ff",
        "graph_gd": "#333333",
    }

    MAX_GRAPH_PTS = 300

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BioPayload Component Dev")
        self.root.geometry("1020x780")
        self.root.minsize(900, 680)
        self.root.configure(bg=self.COLORS["bg"])

        # Serial connections
        self.nano = BoardSerial("Nano", self._on_serial_line, self._on_raw_serial)
        self.uno = BoardSerial("Uno", self._on_serial_line, self._on_raw_serial)

        # Spectral data ring buffer
        self._clear_times: deque[float] = deque(maxlen=self.MAX_GRAPH_PTS)
        self._clear_vals: deque[int] = deque(maxlen=self.MAX_GRAPH_PTS)
        self._t0: Optional[float] = None

        # Polling state
        self._polling = False
        self._poll_after_id: Optional[str] = None

        self._setup_styles()
        self._build_ui()
        self._log("Application started", "info")

    # ------------------------------------------------------------------ styles
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Panel.TFrame", background=self.COLORS["panel"])
        style.configure("Dark.TFrame", background=self.COLORS["bg"])

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
        style.configure("Danger.TButton", font=("Helvetica", 10, "bold"), padding=(15, 8))
        style.configure("Connect.TButton", font=("Helvetica", 10), padding=(10, 5))

    # ---------------------------------------------------------------- top-level layout
    def _build_ui(self):
        main = ttk.Frame(self.root, style="Dark.TFrame", padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_header(main)

        body = ttk.Frame(main, style="Dark.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        # Left column — connections + controls
        left = ttk.Frame(body, style="Dark.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._build_connection_panel(left)
        self._build_pump_panel(left)
        self._build_motor_panel(left)
        self._build_abort_panel(left)

        # Right column — graph + LED + log
        right = ttk.Frame(body, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=0)
        right.rowconfigure(2, weight=1)

        self._build_graph_panel(right)
        self._build_led_panel(right)
        self._build_log_panel(right)

    # ---------------------------------------------------------------- header
    def _build_header(self, parent):
        hdr = ttk.Frame(parent, style="Dark.TFrame")
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Component Dev Station", style="Header.TLabel").pack(side=tk.LEFT)
        tk.Label(hdr, text="dev v0.1", bg=self.COLORS["accent"],
                 fg=self.COLORS["text_dim"], font=("Helvetica", 9),
                 padx=8, pady=2).pack(side=tk.RIGHT)

    # ---------------------------------------------------------------- connections
    def _build_connection_panel(self, parent):
        panel = self._panel(parent, "Connections")

        for board_label, attr_prefix in [("Nano (pump/sensor)", "nano"), ("Uno (stepper)", "uno")]:
            row = ttk.Frame(panel, style="Panel.TFrame")
            row.pack(fill=tk.X, pady=(0, 8))

            ttk.Label(row, text=board_label, style="Dim.TLabel").pack(anchor=tk.W)

            inner = ttk.Frame(row, style="Panel.TFrame")
            inner.pack(fill=tk.X, pady=(2, 0))

            port_var = tk.StringVar()
            combo = ttk.Combobox(inner, textvariable=port_var, state="readonly", width=20)
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

            refresh_btn = ttk.Button(inner, text="⟳", width=3,
                                     command=lambda c=combo, v=port_var: self._refresh_combo(c, v))
            refresh_btn.pack(side=tk.LEFT, padx=4)

            conn_btn = ttk.Button(inner, text="Connect", style="Connect.TButton",
                                  command=lambda a=attr_prefix: self._toggle_conn(a))
            conn_btn.pack(side=tk.LEFT)

            dot = tk.Label(inner, text="●", bg=self.COLORS["panel"],
                           fg=self.COLORS["error"], font=("Helvetica", 12))
            dot.pack(side=tk.LEFT, padx=(6, 0))

            setattr(self, f"_{attr_prefix}_port_var", port_var)
            setattr(self, f"_{attr_prefix}_combo", combo)
            setattr(self, f"_{attr_prefix}_conn_btn", conn_btn)
            setattr(self, f"_{attr_prefix}_dot", dot)

            self._refresh_combo(combo, port_var)

    def _refresh_combo(self, combo, var):
        ports = get_serial_ports()
        combo["values"] = ports if ports else ["No ports"]
        if ports:
            var.set(ports[0])
        else:
            var.set("No ports")

    def _toggle_conn(self, board: str):
        bs: BoardSerial = getattr(self, board)
        btn = getattr(self, f"_{board}_conn_btn")
        dot = getattr(self, f"_{board}_dot")
        port_var: tk.StringVar = getattr(self, f"_{board}_port_var")

        if bs.connected:
            bs.disconnect()
            btn.configure(text="Connect")
            dot.configure(fg=self.COLORS["error"])
            self._log(f"{bs.name} disconnected", "info")
        else:
            port = port_var.get()
            if not port or port == "No ports":
                messagebox.showerror("Error", f"No port selected for {bs.name}")
                return
            self._log(f"Connecting {bs.name} on {port}…", "info")
            if bs.connect(port):
                btn.configure(text="Disconnect")
                dot.configure(fg=self.COLORS["success"])
                self._log(f"{bs.name} connected", "success")
                bs.send("PING")
            else:
                self._log(f"{bs.name} connection failed", "error")

    # ---------------------------------------------------------------- pump controls
    def _build_pump_panel(self, parent):
        panel = self._panel(parent, "Pump (Nano)")

        dur_frame = ttk.Frame(panel, style="Panel.TFrame")
        dur_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(dur_frame, text="Duration:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._pump_dur_var = tk.IntVar(value=3000)
        spin = ttk.Spinbox(dur_frame, from_=100, to=60000, increment=100,
                           textvariable=self._pump_dur_var, width=8,
                           font=("Helvetica", 11))
        spin.pack(side=tk.LEFT, padx=(6, 2))
        ttk.Label(dur_frame, text="ms", style="Dim.TLabel").pack(side=tk.LEFT)

        self._pump_btn = ttk.Button(panel, text="▶  Run Pump",
                                    style="Primary.TButton",
                                    command=self._run_pump)
        self._pump_btn.pack(fill=tk.X)

    def _run_pump(self):
        if not self.nano.connected:
            messagebox.showwarning("Not connected", "Nano is not connected")
            return
        dur = self._pump_dur_var.get()
        self.nano.send(f"PUMP {dur}")
        self._log(f"Pump started for {dur} ms", "info")

    # ---------------------------------------------------------------- motor controls
    def _build_motor_panel(self, parent):
        panel = self._panel(parent, "Stepper Motor (Uno)")

        btn_frame = ttk.Frame(panel, style="Panel.TFrame")
        btn_frame.pack(fill=tk.X)

        self._motor_fwd_btn = ttk.Button(btn_frame, text="▶ Forward",
                                         style="Primary.TButton",
                                         command=lambda: self._motor_cmd("f", "forward"))
        self._motor_fwd_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self._motor_rev_btn = ttk.Button(btn_frame, text="◀ Reverse",
                                         style="Primary.TButton",
                                         command=lambda: self._motor_cmd("r", "reverse"))
        self._motor_rev_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 4))

        self._motor_stop_btn = ttk.Button(btn_frame, text="■ Stop",
                                          command=lambda: self._motor_cmd("s", "stop"))
        self._motor_stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

    def _motor_cmd(self, cmd: str, label: str):
        if not self.uno.connected:
            messagebox.showwarning("Not connected", "Uno is not connected")
            return
        self.uno.send(cmd)
        self._log(f"Motor {label}", "info")

    # ---------------------------------------------------------------- abort
    def _build_abort_panel(self, parent):
        panel = self._panel(parent, "Emergency")

        abort_btn = tk.Button(
            panel, text="ABORT ALL", font=("Helvetica", 13, "bold"),
            bg="#b71c1c", fg="white", activebackground="#d32f2f",
            activeforeground="white", relief=tk.FLAT, pady=8,
            command=self._abort_all,
        )
        abort_btn.pack(fill=tk.X)

    def _abort_all(self):
        if self.nano.connected:
            self.nano.send("ABORT")
        if self.uno.connected:
            self.uno.send("s")
        self._log("ABORT ALL sent", "warning")

    # ---------------------------------------------------------------- graph
    def _build_graph_panel(self, parent):
        panel = self._panel(parent, "Spectral Sensor — Clear Channel", expand=True)

        # Toolbar row
        toolbar = ttk.Frame(panel, style="Panel.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 6))

        self._poll_btn = ttk.Button(toolbar, text="▶ Start Polling",
                                    command=self._toggle_polling)
        self._poll_btn.pack(side=tk.LEFT)

        ttk.Label(toolbar, text="  Interval:", style="Dim.TLabel").pack(side=tk.LEFT)
        self._poll_interval_var = tk.IntVar(value=1000)
        intv_spin = ttk.Spinbox(toolbar, from_=250, to=5000, increment=250,
                                textvariable=self._poll_interval_var, width=6,
                                font=("Helvetica", 10))
        intv_spin.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(toolbar, text="ms", style="Dim.TLabel").pack(side=tk.LEFT)

        clear_btn = ttk.Button(toolbar, text="Clear", command=self._clear_graph)
        clear_btn.pack(side=tk.RIGHT)

        self._latest_clear_label = tk.Label(
            toolbar, text="Clear: --", bg=self.COLORS["panel"],
            fg=self.COLORS["graph_ln"], font=("Consolas", 12, "bold"))
        self._latest_clear_label.pack(side=tk.RIGHT, padx=(0, 12))

        # Matplotlib figure
        self._fig = Figure(figsize=(6, 2.4), dpi=100, facecolor=self.COLORS["graph_bg"])
        self._ax = self._fig.add_subplot(111)
        self._style_axes()
        self._canvas = FigureCanvasTkAgg(self._fig, master=panel)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _style_axes(self):
        ax = self._ax
        ax.set_facecolor(self.COLORS["graph_bg"])
        ax.tick_params(colors=self.COLORS["text_dim"], labelsize=8)
        ax.set_xlabel("Time (s)", color=self.COLORS["text_dim"], fontsize=9)
        ax.set_ylabel("Clear", color=self.COLORS["text_dim"], fontsize=9)
        for spine in ax.spines.values():
            spine.set_color(self.COLORS["graph_gd"])
        ax.grid(True, color=self.COLORS["graph_gd"], linewidth=0.4, alpha=0.6)

    def _toggle_polling(self):
        if self._polling:
            self._stop_polling()
        else:
            self._start_polling()

    def _start_polling(self):
        if not self.nano.connected:
            messagebox.showwarning("Not connected", "Nano is not connected")
            return
        self._polling = True
        self._poll_btn.configure(text="■ Stop Polling")
        if self._t0 is None:
            self._t0 = time.time()
        self._poll_tick()

    def _stop_polling(self):
        self._polling = False
        self._poll_btn.configure(text="▶ Start Polling")
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None

    def _poll_tick(self):
        if not self._polling:
            return
        if self.nano.connected:
            self.nano.send("SPEC")
        interval = self._poll_interval_var.get()
        self._poll_after_id = self.root.after(interval, self._poll_tick)

    def _push_clear(self, value: int):
        now = time.time()
        if self._t0 is None:
            self._t0 = now
        self._clear_times.append(now - self._t0)
        self._clear_vals.append(value)
        self._redraw_graph()
        self._latest_clear_label.configure(text=f"Clear: {value}")

    def _redraw_graph(self):
        ax = self._ax
        ax.cla()
        self._style_axes()
        if self._clear_times:
            ax.plot(list(self._clear_times), list(self._clear_vals),
                    color=self.COLORS["graph_ln"], linewidth=1.4)
            ax.fill_between(list(self._clear_times), list(self._clear_vals),
                            color=self.COLORS["graph_ln"], alpha=0.08)
        self._fig.tight_layout(pad=1.0)
        self._canvas.draw_idle()

    def _clear_graph(self):
        self._clear_times.clear()
        self._clear_vals.clear()
        self._t0 = None
        self._redraw_graph()
        self._latest_clear_label.configure(text="Clear: --")

    # ---------------------------------------------------------------- LED status
    def _build_led_panel(self, parent):
        panel = self._panel(parent, "LED Status (pot-controlled)", expand=False)

        row = ttk.Frame(panel, style="Panel.TFrame")
        row.pack(fill=tk.X)

        self._led_hue_label = tk.Label(row, text="Hue: --",
                                       bg=self.COLORS["panel"],
                                       fg=self.COLORS["text"],
                                       font=("Consolas", 11))
        self._led_hue_label.pack(side=tk.LEFT, padx=(0, 16))

        self._led_rgb_label = tk.Label(row, text="RGB: --",
                                       bg=self.COLORS["panel"],
                                       fg=self.COLORS["text"],
                                       font=("Consolas", 11))
        self._led_rgb_label.pack(side=tk.LEFT, padx=(0, 16))

        self._led_swatch = tk.Canvas(row, width=28, height=28,
                                     bg=self.COLORS["panel"],
                                     highlightthickness=0)
        self._led_swatch.pack(side=tk.LEFT)
        self._swatch_rect = self._led_swatch.create_rectangle(
            2, 2, 26, 26, fill="#000000", outline=self.COLORS["accent"])

        query_btn = ttk.Button(row, text="Query LED", command=self._query_led)
        query_btn.pack(side=tk.RIGHT)

    def _query_led(self):
        if not self.nano.connected:
            messagebox.showwarning("Not connected", "Nano is not connected")
            return
        self.nano.send("LED")

    def _update_led_display(self, info: dict):
        self._led_hue_label.configure(text=f"Hue: {info['hue']:.1f}°")
        self._led_rgb_label.configure(text=f"RGB: {info['r']},{info['g']},{info['b']}")
        hex_color = f"#{info['r']:02x}{info['g']:02x}{info['b']:02x}"
        self._led_swatch.itemconfigure(self._swatch_rect, fill=hex_color)

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
            ("tx",      "#82aaff"),
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

    # ---------------------------------------------------------------- serial callbacks
    def _on_raw_serial(self, board: str, direction: str, text: str):
        tag = "tx" if direction == "TX" else "rx"
        arrow = "→" if direction == "TX" else "←"
        self.root.after(0, lambda: self._log(f"[{board}] {direction} {arrow} {text}", tag))

    def _on_serial_line(self, board: str, line: str):
        self.root.after(0, lambda: self._dispatch_line(board, line))

    def _dispatch_line(self, board: str, line: str):
        if board == "Nano":
            spec = parse_spectral(line)
            if spec is not None:
                self._push_clear(spec["clear"])
                return

            led = parse_led(line)
            if led is not None:
                self._update_led_display(led)
                return

            if line == "ACK PUMP":
                self._log("Pump finished", "success")
            elif line == "ACK ABORT":
                self._log("Nano abort acknowledged", "warning")
            elif line == "ACK SPEC":
                pass  # graph already updated from the data line
            elif line.startswith("ERR"):
                self._log(f"Nano: {line}", "error")

        elif board == "Uno":
            low = line.lower()
            if "forward" in low:
                self._log("Motor running forward", "success")
            elif "reverse" in low:
                self._log("Motor running reverse", "success")
            elif "stopped" in low or "stop" in low:
                self._log("Motor stopped", "info")
            elif line.startswith("ERR"):
                self._log(f"Uno: {line}", "error")


# ============================================================================
# Entry point
# ============================================================================

def main():
    root = tk.Tk()
    app = ComponentDevApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: _on_close(app, root))
    root.mainloop()


def _on_close(app: ComponentDevApp, root: tk.Tk):
    app._stop_polling()
    app.nano.disconnect()
    app.uno.disconnect()
    root.destroy()


if __name__ == "__main__":
    main()
