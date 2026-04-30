# BioPayload — Senior Design 2025–2026

An embedded biology payload system for automated well-plate scanning. An Arduino Nano ESP32 drives a stepper-motor linear stage, RGB LED backlight, AS7341 spectral sensor, peristaltic pump, and SD card logger. A Python ground-station application connects over USB serial to visualize sensor data in real time and issue commands.

---

## Table of Contents

1. [Setup Guide](#setup-guide)
   - [Prerequisites](#prerequisites)
   - [Firmware Setup (PlatformIO)](#firmware-setup-platformio)
   - [Python Ground Station Setup](#python-ground-station-setup)
2. [Usage](#usage)
   - [Flashing Firmware](#flashing-firmware)
   - [Serial Commands](#serial-commands)
   - [Running the Live Plot](#running-the-live-plot)
   - [Running the GUI](#running-the-gui)
3. [Repository Structure](#repository-structure)

---

## Setup Guide

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html) | ≥ 6.x | CLI or VS Code extension |
| Python | ≥ 3.10 | For ground station scripts |
| Arduino Nano ESP32 | — | Payload MCU (USB-C) |

---

### Firmware Setup (PlatformIO)

1. **Clone the repo and navigate to the firmware directory:**

   ```bash
   cd biopayload/firmware
   ```

2. **Install PlatformIO** (if not already installed):

   ```bash
   pip install platformio
   ```

3. **Install library dependencies** — PlatformIO handles this automatically on first build. The main dependencies are:
   - `adafruit/Adafruit AS7341` — spectral sensor driver
   - `arduino-libraries/SD` — SD card support
   - `bblanchon/ArduinoJson` — JSON serialization

4. **Connect the Arduino Nano ESP32** via USB-C. On macOS it will appear as `/dev/cu.usbmodem*`.

---

### Python Ground Station Setup

1. **Navigate to the home directory:**

   ```bash
   cd biopayload/home
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   Key packages: `pyserial`, `matplotlib`, `numpy`.

---

## Usage

### Flashing Firmware

The single firmware target is defined in `biopayload/firmware/platformio.ini`. From the `biopayload/firmware/` directory:

| Target | Board | Command |
|--------|-------|---------|
| `component_dev` | Arduino Nano ESP32 | `pio run -e component_dev -t upload` |

`component_dev` performs full well-plate scans and logs results to SD card. It is also the default env, so `pio run -t upload` is equivalent.

To open the serial monitor after uploading:

```bash
pio device monitor -e component_dev
```

---

### Serial Commands

Once `component_dev` firmware is running, send single-character commands over serial (115200 baud):

| Key | Action |
|-----|--------|
| `s` | Start a 39-second well-plate scan |
| `r` | Reverse stepper direction (aborts active scan) |
| `p` | Pause / resume stepper (aborts active scan if one is running) |
| `m` | Toggle peristaltic pump on/off |
| `x` | Stop stepper and abort active scan |

**Scan output format:**

```
SCAN_START
SCAN T:<elapsed_ms> 415nm:<v> 445nm:<v> ... 590nm:<v> ...
SCAN_DONE
WELL 1 590nm=<avg> n=<samples>
WELL 2 590nm=<avg> n=<samples>
WELL 3 590nm=<avg> n=<samples>
WELL 4 590nm=<avg> n=<samples>
SD_OK /scan_001.csv
```

Results are saved to the SD card as `/scan_NNN.csv` with columns `Well`, `590nm_Avg`, `Samples`.

---

### Running the Live Plot

`live_clear_plot.py` connects to the firmware over serial and plots the AS7341 590 nm channel in real time, along with a computed transmission ratio relative to a hardcoded blank.

```bash
cd biopayload/home
python live_clear_plot.py              # auto-detects /dev/cu.usbmodem*
python live_clear_plot.py /dev/cu.usbmodem1234  # specify port manually
```

While the plot is open, press keys in the terminal (no Enter needed):

| Key | Action |
|-----|--------|
| `r` | Reverse stepper direction |
| `p` | Pause / resume stepper |
| `Ctrl+C` | Exit |

To adjust the blank reference value, edit `BLANK_I0` at the top of `live_clear_plot.py`.

---

### Running the GUI

A Tkinter-based GUI for component-level testing is available:

```bash
cd biopayload/home
python component_dev_gui.py
```

The GUI provides:
- Live view of the AS7341 clear channel reading
- Pump control (on for N milliseconds)
- Stepper jog controls (forward / reverse / stop)
- RGB LED readout
- Emergency abort button

A well-plate scan GUI is also available:

```bash
python wellplate_gui.py
```

---

## Repository Structure

```
biopayload/
├── firmware/                   # PlatformIO firmware project (Nano ESP32 only)
│   ├── platformio.ini          # Single env: component_dev
│   ├── src/
│   │   ├── main_component_dev.cpp   # Primary demo: well-plate scan
│   │   └── components/
│   │       ├── spectral_sensor.h    # AS7341 wrapper
│   │       ├── linear_actuator.h    # Stepper motor abstraction
│   │       └── peristaltic_pump.{h,cpp}  # Pump abstraction
│   ├── include/                # Header search-path stub
│   └── lib/                    # Private project libraries (PlatformIO)
│
├── home/                       # Python ground station
│   ├── live_clear_plot.py      # Real-time 590nm + transmission plot
│   ├── component_dev_gui.py    # Tkinter GUI for component testing
│   ├── wellplate_gui.py        # Tkinter GUI for well-plate scans
│   ├── main.py                 # Entry point / legacy GUI
│   └── requirements.txt        # Python dependencies
│
├── diagram/
│   ├── class_diagram.puml      # PlantUML class diagram
│   └── comm_protocol.dot       # Graphviz communication protocol diagram
│
└── MVP.md                      # Communication protocol & system design spec
```

### Pin Reference (Nano ESP32 — `component_dev`)

| Signal | Pin |
|--------|-----|
| RGB LED Red | A1 |
| RGB LED Green | A0 |
| RGB LED Blue | A2 |
| AS7341 SDA | A4 |
| AS7341 SCL | A5 |
| Stepper STEP | 4 |
| Stepper DIR | 2 |
| Stepper EN | 3 |
| Pump | D5 |
| SD CS | D7 |
| SD CLK | 10 |
| SD MISO | D9 |
| SD MOSI | D8 |
