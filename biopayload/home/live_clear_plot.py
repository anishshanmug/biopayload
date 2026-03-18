"""
Live OD600 plot with command input.

Plots AS7341 590nm channel and computes OD against a hardcoded blank.

Usage:
    python live_clear_plot.py [port]
"""

import sys
import glob
import re
import time
import math
import threading
import serial
import matplotlib.pyplot as plt
from collections import deque

BAUD = 115200
MAX_POINTS = 50
BLANK_I0 = 325  # blank = solid well plate material (minimum transmission)

def find_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    ports = glob.glob("/dev/cu.usbmodem*")
    if not ports:
        print("No /dev/cu.usbmodem* port found. Pass port as argument.")
        sys.exit(1)
    return ports[0]

def command_input_thread(ser, running):
    """Reads single-char commands from stdin and sends immediately over serial."""
    import tty, termios, select
    print("\n--- Command input ready ---")
    print("  r = reverse   p = pause/resume stepper")
    print("  Press a key (no Enter needed).\n")

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while running[0]:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                c = sys.stdin.read(1)
                if c in ('r', 'R', 'p', 'P'):
                    ser.write((c + "\n").encode())
                elif c in ('\x03', '\x04'):  # Ctrl+C / Ctrl+D
                    running[0] = False
                    break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def main():
    port = find_port()
    print(f"Connecting to {port} at {BAUD} baud...")
    print(f"Blank I0 = {BLANK_I0} (hardcoded)")

    ser = serial.Serial(port, BAUD, timeout=0.5)
    ser.dtr = True
    ser.rts = True
    time.sleep(2)
    ser.reset_input_buffer()

    running = [True]
    cmd_thread = threading.Thread(target=command_input_thread, args=(ser, running), daemon=True)
    cmd_thread.start()

    plt.ion()
    fig, (ax_raw, ax_od) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    fig.suptitle("Well Plate Scan (590nm, Red LED)  |  r=reverse  p=pause")

    raw_vals = deque(maxlen=MAX_POINTS)
    od_vals  = deque(maxlen=MAX_POINTS)

    line_raw, = ax_raw.plot([], [], color="red", linewidth=2)
    ax_raw.set_ylabel("590nm raw")
    ax_raw.axhline(BLANK_I0, color="gray", linestyle="--", linewidth=1, label=f"blank={BLANK_I0}")
    ax_raw.legend(loc="upper right", fontsize=8)

    line_od, = ax_od.plot([], [], color="darkblue", linewidth=2)
    ax_od.set_ylabel("Transmission (I/I₀)")
    ax_od.set_xlabel("Sample")
    ax_od.axhline(1.0, color="gray", linestyle="--", linewidth=1, label="blank=1.0")
    ax_od.legend(loc="upper right", fontsize=8)
    ax_od.set_ylim(0.8, 5.0)

    pattern = re.compile(r"590nm:(\d+)")

    print("Measuring... (press p to start stepper)\n")
    try:
        while plt.fignum_exists(fig.number):
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
            if not raw:
                plt.pause(0.05)
                continue

            m = pattern.search(raw)
            if not m:
                if any(raw.startswith(k) for k in ("DIR", "PAUSED", "RUNNING", "ACK", "ERR")):
                    print(f"  [{raw}]")
                continue

            val = int(m.group(1))
            raw_vals.append(val)
            # Transmission relative to blank (solid plate = 1.0, open wells > 1.0)
            transmission = val / BLANK_I0
            od_vals.append(transmission)

            xs = list(range(len(raw_vals)))
            line_raw.set_data(xs, list(raw_vals))
            ax_raw.set_xlim(0, max(MAX_POINTS, len(raw_vals)))
            lo = max(0, min(raw_vals) - 200)
            hi = min(65535, max(raw_vals) + 200)
            ax_raw.set_ylim(lo if lo != hi else lo - 50, hi if lo != hi else hi + 50)

            line_od.set_data(xs, list(od_vals))
            ax_od.set_xlim(0, max(MAX_POINTS, len(od_vals)))
            if od_vals:
                ax_od.set_ylim(min(od_vals) - 0.1, max(od_vals) + 0.3)

            plt.pause(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        running[0] = False
        ser.close()
        plt.close()
        print("Done.")

if __name__ == "__main__":
    main()
