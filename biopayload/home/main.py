#!/usr/bin/env python3
"""
BioPayload Ground Station - MVP Demo
A polished GUI for controlling satellite biology experiments.

This demo simulates the full workflow without requiring Arduino hardware.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import threading
import time
import random
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional
import uuid
import serial
import serial.tools.list_ports


# ============================================================================
# Configuration & Data Classes
# ============================================================================

@dataclass
class ExperimentConfig:
    """Immutable experiment configuration."""
    run_id: str
    sample_rate_ms: int
    num_challenges: int
    target_temp_c: float
    
    def validate(self) -> tuple[bool, str]:
        """Validate configuration parameters."""
        if self.sample_rate_ms < 100:
            return False, "Sample rate must be at least 100ms"
        if self.sample_rate_ms > 60000:
            return False, "Sample rate cannot exceed 60 seconds"
        if self.num_challenges < 1:
            return False, "Must have at least 1 challenge"
        if self.num_challenges > 100:
            return False, "Cannot exceed 100 challenges"
        if self.target_temp_c < 15.0:
            return False, "Temperature must be at least 15°C"
        if self.target_temp_c > 45.0:
            return False, "Temperature cannot exceed 45°C"
        return True, "Valid"


# ============================================================================
# Simulated Payload (Replace with real serial later)
# ============================================================================

class SimulatedPayload:
    """
    Simulates Arduino Nano responses for demo purposes.
    This will be replaced with real serial communication.
    """
    
    def __init__(self, on_message):
        self.on_message = on_message  # Callback for messages to GUI
        self.state = "IDLE"
        self.config: Optional[ExperimentConfig] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.current_temp = 22.0
        self.challenge_index = 0
        
    def send_command(self, command: str, payload: dict = None):
        """Process a command and respond."""
        # Simulate slight delay
        time.sleep(0.05)
        
        if command == "HELLO":
            self.on_message("ACK", {"command": "HELLO", "firmware": "1.0.0"})
            
        elif command == "SET_CONFIG":
            if self.state != "IDLE":
                self.on_message("ERR", {"code": "BUSY", "message": "Cannot configure while running"})
            else:
                self.config = ExperimentConfig(**payload)
                self.on_message("ACK", {"command": "SET_CONFIG"})
                
        elif command == "START":
            if self.config is None:
                self.on_message("ERR", {"code": "NO_CONFIG", "message": "No configuration set"})
            elif self.state != "IDLE":
                self.on_message("ERR", {"code": "BUSY", "message": "Already running"})
            else:
                self.state = "RUNNING"
                self.on_message("ACK", {"command": "START"})
                self.on_message("STATE", {"state": "RUNNING"})
                self._start_experiment()
                
        elif command == "ABORT":
            self._stop_experiment()
            self.state = "IDLE"
            self.on_message("ACK", {"command": "ABORT"})
            self.on_message("STATE", {"state": "IDLE"})
            
        elif command == "PING":
            self.on_message("ACK", {"command": "PING", "state": self.state})
            
    def _start_experiment(self):
        """Run simulated experiment in background thread."""
        self.running = True
        self.challenge_index = 0
        self.current_temp = 22.0
        self.thread = threading.Thread(target=self._experiment_loop, daemon=True)
        self.thread.start()
        
    def _stop_experiment(self):
        """Stop the experiment."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            
    def _experiment_loop(self):
        """Simulate experiment execution."""
        start_time = time.time()
        
        while self.running and self.challenge_index < self.config.num_challenges:
            # Simulate temperature approaching target
            temp_diff = self.config.target_temp_c - self.current_temp
            self.current_temp += temp_diff * 0.1 + random.uniform(-0.2, 0.2)
            
            # Generate telemetry
            elapsed = time.time() - start_time
            telem = {
                "run_id": self.config.run_id,
                "timestamp": datetime.now().isoformat(),
                "elapsed_s": round(elapsed, 2),
                "temperature_c": round(self.current_temp, 2),
                "target_temp_c": self.config.target_temp_c,
                "challenge_index": self.challenge_index + 1,
                "total_challenges": self.config.num_challenges,
                "sensor_1": round(random.uniform(0.8, 1.2), 3),
                "sensor_2": round(random.uniform(45, 55), 1),
            }
            self.on_message("TELEM", telem)
            
            # Advance challenge every few samples (simulated)
            if random.random() < 0.15:
                self.challenge_index += 1
                
            # Wait for next sample
            time.sleep(self.config.sample_rate_ms / 1000.0)
            
        if self.running:  # Completed normally
            self.running = False
            self.state = "DONE"
            result = {
                "run_id": self.config.run_id,
                "status": "COMPLETE",
                "challenges_completed": self.config.num_challenges,
                "final_temp_c": round(self.current_temp, 2),
                "duration_s": round(time.time() - start_time, 2),
            }
            self.on_message("RESULT", result)
            self.on_message("STATE", {"state": "DONE"})


# ============================================================================
# Real Serial Payload
# ============================================================================

class SerialPayload:
    """
    Real Arduino Nano communication over serial.
    """
    
    def __init__(self, port: str, on_message, on_raw_message=None, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.on_message = on_message
        self.on_raw_message = on_raw_message  # Callback for raw TX/RX logging
        self.serial: Optional[serial.Serial] = None
        self.running = False
        self.reader_thread: Optional[threading.Thread] = None
        
    def connect(self) -> bool:
        """Open serial connection."""
        try:
            self.serial = serial.Serial(
                self.port, 
                self.baudrate, 
                timeout=0.1
            )
            time.sleep(2)  # Wait for Arduino reset
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            return True
        except serial.SerialException as e:
            self.on_message("ERR", {"code": "SERIAL", "message": str(e)})
            return False
            
    def disconnect(self):
        """Close serial connection."""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=1.0)
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.serial = None
        
    def send_command(self, command: str, payload: dict = None):
        """Send a command to the Arduino."""
        if not self.serial or not self.serial.is_open:
            self.on_message("ERR", {"code": "NOT_CONNECTED", "message": "Serial not connected"})
            return
            
        try:
            if command == "SET_CONFIG" and payload:
                # Send config as JSON
                config_json = json.dumps(payload)
                line = f"SET_CONFIG {config_json}\n"
            else:
                line = f"{command}\n"
            
            # Log outgoing message
            if self.on_raw_message:
                self.on_raw_message("TX", line.strip())
            
            self.serial.write(line.encode())
        except serial.SerialException as e:
            self.on_message("ERR", {"code": "SERIAL", "message": str(e)})
            
    def _read_loop(self):
        """Background thread to read serial messages."""
        buffer = ""
        while self.running and self.serial and self.serial.is_open:
            try:
                if self.serial.in_waiting:
                    data = self.serial.read(self.serial.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            self._parse_message(line)
                else:
                    time.sleep(0.01)
            except serial.SerialException:
                break
                
    def _parse_message(self, line: str):
        """Parse a message from the Arduino."""
        # Log incoming message
        if self.on_raw_message:
            self.on_raw_message("RX", line)
        
        parts = line.split(' ', 1)
        msg_type = parts[0]
        
        if msg_type == "ACK":
            rest = parts[1] if len(parts) > 1 else ""
            # "HELLO 1.0.0" -> command=HELLO, firmware=1.0.0
            if rest.startswith("HELLO "):
                cmd = "HELLO"
                firmware = rest[6:].strip() or "unknown"
                self.on_message("ACK", {"command": cmd, "firmware": firmware})
            else:
                self.on_message("ACK", {"command": rest})
            
        elif msg_type == "ERR":
            try:
                data = json.loads(parts[1]) if len(parts) > 1 else {}
            except json.JSONDecodeError:
                data = {"message": parts[1] if len(parts) > 1 else "Unknown error"}
            self.on_message("ERR", data)
            
        elif msg_type == "STATE":
            state = parts[1] if len(parts) > 1 else "UNKNOWN"
            self.on_message("STATE", {"state": state})
            
        elif msg_type == "TELEM":
            try:
                data = json.loads(parts[1]) if len(parts) > 1 else {}
                # Add timestamp if not present
                if "timestamp" not in data:
                    data["timestamp"] = datetime.now().isoformat()
                self.on_message("TELEM", data)
            except json.JSONDecodeError:
                pass
                
        elif msg_type == "RESULT":
            try:
                data = json.loads(parts[1]) if len(parts) > 1 else {}
                self.on_message("RESULT", data)
            except json.JSONDecodeError:
                pass


def get_serial_ports() -> list[str]:
    """Get list of available serial ports."""
    ports = []
    for port in serial.tools.list_ports.comports():
        # Filter out Bluetooth and other non-USB ports
        if 'Bluetooth' not in port.description and 'debug' not in port.device:
            ports.append(port.device)
    return ports


# ============================================================================
# Main Application
# ============================================================================

class BioPayloadApp:
    """Main application window."""
    
    # Color scheme - dark grey
    COLORS = {
        "bg": "#121212",
        "panel": "#1e1e1e",
        "accent": "#2d2d2d",
        "primary": "#e0e0e0",
        "success": "#4caf50",
        "warning": "#ff9800",
        "error": "#f44336",
        "text": "#e0e0e0",
        "text_dim": "#888888",
        "idle": "#666666",
        "running": "#4caf50",
        "done": "#64b5f6",
    }
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BioPayload Ground Station")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg=self.COLORS["bg"])
        
        # State
        self.connected = False
        self.payload: Optional[SerialPayload] = None
        self.current_state = "DISCONNECTED"
        self.scheduled_time: Optional[datetime] = None
        self.schedule_thread: Optional[threading.Thread] = None
        
        # Configure styles
        self._setup_styles()
        
        # Build UI
        self._build_ui()
        
        # Log startup
        self._log_event("Application started", "info")
        
    def _setup_styles(self):
        """Configure ttk styles for modern look."""
        style = ttk.Style()
        style.theme_use("clam")
        
        # Frame styles
        style.configure("Panel.TFrame", background=self.COLORS["panel"])
        style.configure("Dark.TFrame", background=self.COLORS["bg"])
        
        # Label styles
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
                       
        # Button styles
        style.configure("Primary.TButton",
                       font=("Helvetica", 10, "bold"),
                       padding=(15, 8))
        style.configure("Danger.TButton",
                       font=("Helvetica", 10, "bold"),
                       padding=(15, 8))
        style.configure("Connect.TButton",
                       font=("Helvetica", 10),
                       padding=(12, 6))
                       
        # Entry styles
        style.configure("Config.TEntry",
                       font=("Helvetica", 11),
                       padding=5)
                       
        # Spinbox
        style.configure("Config.TSpinbox",
                       font=("Helvetica", 11),
                       padding=5)
        
    def _build_ui(self):
        """Build the main UI layout."""
        # Main container with padding
        main = ttk.Frame(self.root, style="Dark.TFrame", padding=15)
        main.pack(fill=tk.BOTH, expand=True)
        
        # Header
        self._build_header(main)
        
        # Content area - two columns
        content = ttk.Frame(main, style="Dark.TFrame")
        content.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)
        
        # Left column - Config and Controls
        left = ttk.Frame(content, style="Dark.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        
        self._build_connection_panel(left)
        self._build_config_panel(left)
        self._build_control_panel(left)
        
        # Right column - Status and Telemetry
        right = ttk.Frame(content, style="Dark.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.rowconfigure(1, weight=1)
        
        self._build_status_panel(right)
        self._build_telemetry_panel(right)
        self._build_log_panel(right)
        
    def _build_header(self, parent):
        """Build the header bar."""
        header = ttk.Frame(parent, style="Dark.TFrame")
        header.pack(fill=tk.X)
        
        # Title
        title = ttk.Label(header, text="BioPayload Ground Station",
                         style="Header.TLabel")
        title.pack(side=tk.LEFT)
        
        # Version badge
        version_badge = tk.Label(header, text="MVP v0.1", 
                                bg=self.COLORS["accent"], fg=self.COLORS["text_dim"],
                                font=("Helvetica", 9),
                                padx=8, pady=2)
        version_badge.pack(side=tk.RIGHT)
        
    def _build_connection_panel(self, parent):
        """Build the connection status panel."""
        panel = self._create_panel(parent, "Connection")
        
        # Port selection
        port_frame = ttk.Frame(panel, style="Panel.TFrame")
        port_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(port_frame, text="Port:", style="Dim.TLabel").pack(side=tk.LEFT)
        
        # Refresh button
        refresh_btn = ttk.Button(port_frame, text="⟳", width=3,
                                command=self._refresh_ports)
        refresh_btn.pack(side=tk.RIGHT, padx=(4, 0))
        
        # Port dropdown
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.port_var,
                                       state="readonly", width=20)
        self.port_combo.pack(side=tk.RIGHT)
        self._refresh_ports()
        
        # Connect button
        self.connect_btn = ttk.Button(panel, text="Connect", 
                                      style="Connect.TButton",
                                      command=self._toggle_connection)
        self.connect_btn.pack(fill=tk.X)
        
        # Status indicator
        self.conn_status = tk.Label(panel, text="● Disconnected",
                                   bg=self.COLORS["panel"],
                                   fg=self.COLORS["error"],
                                   font=("Helvetica", 10))
        self.conn_status.pack(pady=(8, 0))
        
    def _refresh_ports(self):
        """Refresh the list of available serial ports."""
        ports = get_serial_ports()
        self.port_combo['values'] = ports if ports else ["No ports found"]
        if ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("No ports found")
        
    def _build_config_panel(self, parent):
        """Build the experiment configuration panel."""
        panel = self._create_panel(parent, "Experiment Configuration")
        
        # Run ID (auto-generated)
        self._add_config_row(panel, "Run ID:", self._create_run_id_field)
        
        # Sample Rate
        self._add_config_row(panel, "Sample Rate:", self._create_sample_rate_field)
        
        # Number of Challenges
        self._add_config_row(panel, "Challenges:", self._create_challenges_field)
        
        # Target Temperature
        self._add_config_row(panel, "Target Temp:", self._create_temp_field)
        
    def _add_config_row(self, parent, label, field_factory):
        """Add a labeled config row."""
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=4)
        
        ttk.Label(row, text=label, style="Dim.TLabel", width=12).pack(side=tk.LEFT)
        field_factory(row)
        
    def _create_run_id_field(self, parent):
        """Create run ID field with regenerate button."""
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        self.run_id_var = tk.StringVar(value=self._generate_run_id())
        entry = ttk.Entry(frame, textvariable=self.run_id_var, width=18,
                         font=("Consolas", 10))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        regen_btn = ttk.Button(frame, text="↻", width=3,
                              command=lambda: self.run_id_var.set(self._generate_run_id()))
        regen_btn.pack(side=tk.RIGHT, padx=(4, 0))
        
    def _create_sample_rate_field(self, parent):
        """Create sample rate spinbox."""
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side=tk.RIGHT)
        
        self.sample_rate_var = tk.IntVar(value=1000)
        spin = ttk.Spinbox(frame, from_=100, to=60000, increment=100,
                          textvariable=self.sample_rate_var, width=8,
                          font=("Helvetica", 11))
        spin.pack(side=tk.LEFT)
        ttk.Label(frame, text="ms", style="Dim.TLabel").pack(side=tk.LEFT, padx=(4, 0))
        
    def _create_challenges_field(self, parent):
        """Create challenges spinbox."""
        self.challenges_var = tk.IntVar(value=5)
        spin = ttk.Spinbox(parent, from_=1, to=100, increment=1,
                          textvariable=self.challenges_var, width=8,
                          font=("Helvetica", 11))
        spin.pack(side=tk.RIGHT)
        
    def _create_temp_field(self, parent):
        """Create temperature spinbox."""
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side=tk.RIGHT)
        
        self.temp_var = tk.DoubleVar(value=37.0)
        spin = ttk.Spinbox(frame, from_=15.0, to=45.0, increment=0.5,
                          textvariable=self.temp_var, width=8,
                          font=("Helvetica", 11), format="%.1f")
        spin.pack(side=tk.LEFT)
        ttk.Label(frame, text="°C", style="Dim.TLabel").pack(side=tk.LEFT, padx=(4, 0))
        
    def _build_control_panel(self, parent):
        """Build the experiment control panel."""
        panel = self._create_panel(parent, "Controls")
        
        # Start button
        self.start_btn = ttk.Button(panel, text="▶  Start Experiment",
                                   style="Primary.TButton",
                                   command=self._start_experiment)
        self.start_btn.pack(fill=tk.X, pady=(0, 8))
        self.start_btn.state(["disabled"])
        
        # Abort button
        self.abort_btn = ttk.Button(panel, text="■  Abort",
                                   style="Danger.TButton",
                                   command=self._abort_experiment)
        self.abort_btn.pack(fill=tk.X, pady=(0, 8))
        self.abort_btn.state(["disabled"])
        
        # Scheduler section
        ttk.Separator(panel, orient="horizontal").pack(fill=tk.X, pady=10)
        ttk.Label(panel, text="Schedule Start", style="Dim.TLabel").pack(anchor=tk.W)
        
        sched_frame = ttk.Frame(panel, style="Panel.TFrame")
        sched_frame.pack(fill=tk.X, pady=(4, 0))
        
        self.schedule_var = tk.StringVar(value="")
        sched_entry = ttk.Entry(sched_frame, textvariable=self.schedule_var,
                               width=14, font=("Helvetica", 10))
        sched_entry.pack(side=tk.LEFT)
        sched_entry.insert(0, "HH:MM:SS")
        sched_entry.bind("<FocusIn>", lambda e: sched_entry.delete(0, tk.END) 
                        if sched_entry.get() == "HH:MM:SS" else None)
        
        self.schedule_btn = ttk.Button(sched_frame, text="Schedule",
                                      command=self._schedule_experiment)
        self.schedule_btn.pack(side=tk.RIGHT)
        self.schedule_btn.state(["disabled"])
        
        self.schedule_label = ttk.Label(panel, text="", style="Dim.TLabel")
        self.schedule_label.pack(anchor=tk.W, pady=(4, 0))
        
    def _build_status_panel(self, parent):
        """Build the status display panel."""
        panel = self._create_panel(parent, "Payload Status", expand=False)
        
        # Status grid
        grid = ttk.Frame(panel, style="Panel.TFrame")
        grid.pack(fill=tk.X)
        
        # State indicator (large)
        state_frame = ttk.Frame(grid, style="Panel.TFrame")
        state_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.state_label = tk.Label(state_frame, text="DISCONNECTED",
                                   bg=self.COLORS["panel"],
                                   fg=self.COLORS["idle"],
                                   font=("Helvetica", 24, "bold"))
        self.state_label.pack(side=tk.LEFT)
        
        # Metrics row
        metrics = ttk.Frame(grid, style="Panel.TFrame")
        metrics.pack(fill=tk.X)
        
        self.temp_display = self._create_metric(metrics, "Temperature", "--.- °C")
        self.challenge_display = self._create_metric(metrics, "Challenge", "- / -")
        self.elapsed_display = self._create_metric(metrics, "Elapsed", "--:--")
        
    def _create_metric(self, parent, label, initial):
        """Create a metric display widget."""
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        ttk.Label(frame, text=label, style="Dim.TLabel").pack()
        value_label = tk.Label(frame, text=initial,
                              bg=self.COLORS["panel"],
                              fg=self.COLORS["text"],
                              font=("Consolas", 14))
        value_label.pack()
        return value_label
        
    def _build_telemetry_panel(self, parent):
        """Build the telemetry display panel."""
        panel = self._create_panel(parent, "Live Telemetry", expand=True)
        
        # Telemetry text area
        text_frame = ttk.Frame(panel, style="Panel.TFrame")
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        self.telem_text = tk.Text(text_frame, height=8, 
                                 bg=self.COLORS["bg"],
                                 fg=self.COLORS["text"],
                                 font=("Consolas", 10),
                                 state=tk.DISABLED,
                                 wrap=tk.NONE)
        self.telem_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                 command=self.telem_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.telem_text.configure(yscrollcommand=scrollbar.set)
        
        # Header
        self._append_telemetry("TIME        | TEMP   | SENSOR1 | SENSOR2 | CHALLENGE")
        self._append_telemetry("-" * 58)
        
    def _build_log_panel(self, parent):
        """Build the event log panel."""
        panel = self._create_panel(parent, "Event Log", expand=True)
        
        self.log_text = tk.Text(panel, height=6,
                               bg=self.COLORS["bg"],
                               fg=self.COLORS["text_dim"],
                               font=("Consolas", 9),
                               state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure tags for colored log entries
        self.log_text.tag_configure("info", foreground=self.COLORS["text"])
        self.log_text.tag_configure("success", foreground=self.COLORS["success"])
        self.log_text.tag_configure("warning", foreground=self.COLORS["warning"])
        self.log_text.tag_configure("error", foreground=self.COLORS["error"])
        self.log_text.tag_configure("tx", foreground="#82aaff")  # Blue for outgoing
        self.log_text.tag_configure("rx", foreground="#c3e88d")  # Green for incoming
        
    def _create_panel(self, parent, title, expand=False):
        """Create a styled panel with title."""
        container = ttk.Frame(parent, style="Dark.TFrame")
        container.pack(fill=tk.BOTH, expand=expand, pady=(0, 12))
        
        # Panel with padding
        panel = ttk.Frame(container, style="Panel.TFrame", padding=12)
        panel.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(panel, text=title, style="Title.TLabel").pack(anchor=tk.W, pady=(0, 10))
        
        return panel
        
    # ========================================================================
    # Actions
    # ========================================================================
    
    def _generate_run_id(self) -> str:
        """Generate a unique run ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:6]
        return f"{timestamp}_{short_uuid}"
        
    def _toggle_connection(self):
        """Connect or disconnect from payload."""
        if self.connected:
            self._disconnect()
        else:
            self._connect()
            
    def _connect(self):
        """Establish connection to payload."""
        port = self.port_var.get()
        
        if not port or port == "No ports found":
            messagebox.showerror("Error", "No serial port selected")
            return
            
        self._log_event(f"Connecting to {port}...", "info")
        
        # Create serial payload
        self.payload = SerialPayload(port, self._on_payload_message, self._on_raw_serial)
        
        if not self.payload.connect():
            self._log_event(f"Failed to connect to {port}", "error")
            self.payload = None
            return
        
        # Send HELLO to verify connection
        self.payload.send_command("HELLO")
        
        self.connected = True
        self.current_state = "IDLE"
        
        # Update UI
        self.connect_btn.configure(text="Disconnect")
        self.conn_status.configure(text="● Connected", fg=self.COLORS["success"])
        self.start_btn.state(["!disabled"])
        self.schedule_btn.state(["!disabled"])
        self._update_state_display("IDLE")
        
        self._log_event("Connected successfully", "success")
        
    def _disconnect(self):
        """Disconnect from payload."""
        if self.payload:
            if self.current_state == "RUNNING":
                self.payload.send_command("ABORT")
                time.sleep(0.2)  # Give time for abort to process
            self.payload.disconnect()
            
        self.payload = None
        self.connected = False
        self.current_state = "DISCONNECTED"
        
        # Update UI
        self.connect_btn.configure(text="Connect")
        self.conn_status.configure(text="● Disconnected", fg=self.COLORS["error"])
        self.start_btn.state(["disabled"])
        self.abort_btn.state(["disabled"])
        self.schedule_btn.state(["disabled"])
        self._update_state_display("DISCONNECTED")
        
        self._log_event("Disconnected", "info")
        
    def _start_experiment(self):
        """Start the experiment."""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to payload")
            return
            
        # Build and validate config
        config = ExperimentConfig(
            run_id=self.run_id_var.get(),
            sample_rate_ms=self.sample_rate_var.get(),
            num_challenges=self.challenges_var.get(),
            target_temp_c=self.temp_var.get()
        )
        
        valid, msg = config.validate()
        if not valid:
            messagebox.showerror("Invalid Configuration", msg)
            return
            
        self._log_event(f"Starting experiment: {config.run_id}", "info")
        
        # Send config and start
        self.payload.send_command("SET_CONFIG", asdict(config))
        self.payload.send_command("START")
        
        # Update UI
        self.start_btn.state(["disabled"])
        self.abort_btn.state(["!disabled"])
        self._disable_config_fields()
        
    def _abort_experiment(self):
        """Abort the running experiment."""
        if not self.connected:
            return
            
        if messagebox.askyesno("Confirm Abort", "Are you sure you want to abort the experiment?"):
            self._log_event("Aborting experiment...", "warning")
            self.payload.send_command("ABORT")
            self._enable_config_fields()
            
    def _schedule_experiment(self):
        """Schedule an experiment for a future time."""
        time_str = self.schedule_var.get()
        try:
            # Parse time
            parts = time_str.split(":")
            if len(parts) != 3:
                raise ValueError("Invalid format")
            hour, minute, second = int(parts[0]), int(parts[1]), int(parts[2])
            
            # Calculate target datetime
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            if target <= now:
                target += timedelta(days=1)  # Schedule for tomorrow
                
            self.scheduled_time = target
            self.schedule_label.configure(text=f"Scheduled for {target.strftime('%H:%M:%S')}")
            self._log_event(f"Experiment scheduled for {target.strftime('%H:%M:%S')}", "info")
            
            # Start scheduler thread
            self.schedule_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self.schedule_thread.start()
            
        except (ValueError, IndexError):
            messagebox.showerror("Invalid Time", "Please enter time as HH:MM:SS")
            
    def _scheduler_loop(self):
        """Wait for scheduled time and start experiment."""
        while self.scheduled_time and datetime.now() < self.scheduled_time:
            time.sleep(1)
            remaining = (self.scheduled_time - datetime.now()).seconds
            self.root.after(0, lambda r=remaining: 
                          self.schedule_label.configure(text=f"Starting in {r}s"))
                          
        if self.scheduled_time and self.connected:
            self.root.after(0, self._start_experiment)
            self.scheduled_time = None
            
    def _on_payload_message(self, msg_type: str, data: dict):
        """Handle messages from payload (called from background thread)."""
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._handle_message(msg_type, data))
        
    def _on_raw_serial(self, direction: str, message: str):
        """Log raw serial messages (called from background thread)."""
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._log_serial(direction, message))
        
    def _log_serial(self, direction: str, message: str):
        """Display raw serial message in event log."""
        if direction == "TX":
            self._log_event(f"TX → {message}", "tx")
        else:
            self._log_event(f"RX ← {message}", "rx")
        
    def _handle_message(self, msg_type: str, data: dict):
        """Process payload message on main thread."""
        if msg_type == "ACK":
            cmd = data.get("command", "")
            if cmd == "HELLO":
                fw = data.get("firmware", "unknown")
                self._log_event(f"Payload ready (firmware {fw})", "success")
                
        elif msg_type == "ERR":
            self._log_event(f"Error: {data.get('message', 'Unknown error')}", "error")
            
        elif msg_type == "STATE":
            state = data.get("state", "UNKNOWN")
            self._update_state_display(state)
            self.current_state = state
            
            if state == "DONE":
                self._log_event("Experiment completed", "success")
                self.start_btn.state(["!disabled"])
                self.abort_btn.state(["disabled"])
                self._enable_config_fields()
                # Generate new run ID for next experiment
                self.run_id_var.set(self._generate_run_id())
                
        elif msg_type == "TELEM":
            self._update_telemetry(data)
            
        elif msg_type == "RESULT":
            self._log_event(f"Result: {data.get('challenges_completed')} challenges in "
                          f"{data.get('duration_s')}s", "success")
            
    def _update_state_display(self, state: str):
        """Update the state indicator."""
        colors = {
            "DISCONNECTED": self.COLORS["idle"],
            "IDLE": self.COLORS["idle"],
            "RUNNING": self.COLORS["running"],
            "DONE": self.COLORS["done"],
            "ERROR": self.COLORS["error"],
        }
        self.state_label.configure(text=state, fg=colors.get(state, self.COLORS["text"]))
        
    def _update_telemetry(self, data: dict):
        """Update telemetry displays."""
        # Update metric displays
        temp = data.get("temperature_c", 0)
        self.temp_display.configure(text=f"{temp:.1f} °C")
        
        challenge = data.get("challenge_index", 0)
        total = data.get("total_challenges", 0)
        self.challenge_display.configure(text=f"{challenge} / {total}")
        
        elapsed = data.get("elapsed_s", 0)
        mins, secs = divmod(int(elapsed), 60)
        self.elapsed_display.configure(text=f"{mins:02d}:{secs:02d}")
        
        # Add to telemetry log
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-4]
        sensor1 = data.get("sensor_1", 0)
        sensor2 = data.get("sensor_2", 0)
        line = f"{timestamp} | {temp:5.1f}°C | {sensor1:7.3f} | {sensor2:7.1f} | {challenge}/{total}"
        self._append_telemetry(line)
        
    def _append_telemetry(self, text: str):
        """Append text to telemetry display."""
        self.telem_text.configure(state=tk.NORMAL)
        self.telem_text.insert(tk.END, text + "\n")
        self.telem_text.see(tk.END)
        self.telem_text.configure(state=tk.DISABLED)
        
    def _log_event(self, message: str, level: str = "info"):
        """Add an event to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", level)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        
    def _disable_config_fields(self):
        """Disable config fields during experiment."""
        for child in self.root.winfo_children():
            self._set_state_recursive(child, "disabled", 
                                      ["TSpinbox", "TEntry", "TCombobox"])
                                      
    def _enable_config_fields(self):
        """Re-enable config fields."""
        for child in self.root.winfo_children():
            self._set_state_recursive(child, "!disabled",
                                      ["TSpinbox", "TEntry", "TCombobox"])
                                      
    def _set_state_recursive(self, widget, state, widget_types):
        """Recursively set widget state."""
        widget_class = widget.winfo_class()
        if widget_class in widget_types:
            try:
                widget.state([state])
            except:
                pass
        for child in widget.winfo_children():
            self._set_state_recursive(child, state, widget_types)


# ============================================================================
# Entry Point
# ============================================================================

def main():
    root = tk.Tk()
    
    # Set window icon (if available)
    try:
        # Could add an icon here
        pass
    except:
        pass
        
    app = BioPayloadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
