"""
Well-position calibration sweep for BioPayload.

The optical sensor head is too small to locate wells visually, so this script
does a coarse then optionally fine sweep of the full stage travel while
reading the AS7341 at every stop. The output is a CSV + an interactive
matplotlib plot of 590 nm, 630 nm and Clear vs motor position. Well centres
show up as local peaks (or dips) in one or more channels depending on the
illumination and sample.

Usage
-----
1. Close command_gui.py / pio device monitor (only one owner of the serial port).
2. Run:
       python3 calibrate_wells.py
3. After the coarse sweep the script prints a summary table and opens a plot.
   Identify the approximate well centres from the peaks/dips.
4. Optionally run a fine sweep around each candidate:
       python3 calibrate_wells.py --fine 5000 12000 --step 50
5. Record the final step positions and paste them into your SET_CONFIG wells[].

Flags
-----
  --port             Serial device (auto-detect if omitted)
  --step             Steps between readings for the coarse sweep (default 500)
  --start            First position in steps (default: -(post-home-steps))
  --end              Last position in steps  (default 180000)
  --fine N M         Fine sweep from N to M steps (narrower --step recommended)
  --no-home          Skip homing; sweep from current MOT_POS
  --post-home-steps  Steps the firmware backs up from the limit switch before
                     zeroing the position counter. Must match setPostHomeSteps()
                     in components.cpp (default 9600). Used to set the default
                     sweep start so the full physical range is covered.
  --out FILE         Write readings to FILE (default: sweep_<timestamp>.csv)
  --led R G B        LED levels during sweep (default 128 128 128 white)
  --boot-wait        Boot-wait seconds (default 2.5; use 0 if already running)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

from test_protocol import SerialBus, auto_port, DEFAULT_BAUD, HOME_TIMEOUT


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def send_expect(bus: SerialBus, cmd: str, ack_prefix: str, timeout: float = 3.0) -> str:
    bus.send(cmd)
    return bus.expect(lambda l: l.startswith(ack_prefix), timeout=timeout,
                      description=f"{ack_prefix} for {cmd!r}")


def home_motor(bus: SerialBus) -> None:
    print("Homing motor …", end=" ", flush=True)
    bus.send("MOT_ENABLE")
    bus.expect(lambda l: l == "ACK MOT_ENABLE", timeout=3.0, description="ACK MOT_ENABLE")
    bus.send("MOT_HOME")
    bus.expect(lambda l: l == "ACK MOT_HOME", timeout=3.0, description="ACK MOT_HOME")
    bus.expect(lambda l: l == "DONE MOT_HOME", timeout=HOME_TIMEOUT,
               description="DONE MOT_HOME")
    print("done.")


def get_pos(bus: SerialBus) -> int:
    bus.send("MOT_POS")
    line = bus.expect(lambda l: l.startswith("MOT_POS "), timeout=2.0,
                      description="MOT_POS")
    return int(line.split()[1])


def move_to(bus: SerialBus, target: int, current: int, timeout: float = 30.0) -> None:
    delta = target - current
    if delta == 0:
        return
    bus.send(f"MOT_MOVE {delta}")
    bus.expect(lambda l: l == "ACK MOT_MOVE", timeout=3.0, description="ACK MOT_MOVE")
    bus.expect(lambda l: l == "DONE MOT_MOVE", timeout=timeout,
               description="DONE MOT_MOVE")


def spec_read(bus: SerialBus) -> Optional[dict]:
    """Fire SPEC_READ and return parsed channel dict, or None on error.

    Handles the three possible firmware responses:
      ACK SPEC_READ  → async path: wait for TELEM then DONE SPEC_READ
      ERR <anything> → sensor not ready / read fail; return None
    """
    import json
    bus.send("SPEC_READ")
    first = bus.expect(
        lambda l: l == "ACK SPEC_READ" or l.startswith("ERR "),
        timeout=3.0, description="ACK SPEC_READ or ERR",
    )
    if first.startswith("ERR"):
        return None  # sensor absent / circuit-breaker tripped; skip this point

    # ACK received — wait for the async TELEM + DONE
    line = bus.expect(
        lambda l: l.startswith("TELEM {") or l.startswith("ERR "),
        timeout=3.0, description="TELEM or ERR after ACK SPEC_READ",
    )
    bus.expect(lambda l: l == "DONE SPEC_READ", timeout=2.0,
               description="DONE SPEC_READ")
    if line.startswith("ERR"):
        return None
    try:
        return json.loads(line[6:])  # strip "TELEM "
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run_sweep(bus: SerialBus, positions: list[int], led: tuple[int,int,int]) -> list[dict]:
    """Drive the stage to each position and take a spectral reading.

    Returns a list of dicts: {pos, f1..f8, clear, nir}.
    """
    r, g, b = led
    bus.send(f"LED_SET {r} {g} {b}")
    bus.expect(lambda l: l == "ACK LED_SET", timeout=2.0, description="ACK LED_SET")

    rows = []
    current = get_pos(bus)
    total = len(positions)

    print(f"Sweeping {total} positions …")
    for i, pos in enumerate(positions):
        move_to(bus, pos, current, timeout=60.0)
        current = pos

        reading = spec_read(bus)
        row = {"pos": pos}
        if reading:
            for k in ("f1","f2","f3","f4","f5","f6","f7","f8","clear","nir"):
                row[k] = reading.get(k, 0)
        else:
            for k in ("f1","f2","f3","f4","f5","f6","f7","f8","clear","nir"):
                row[k] = 0
            print(f"  [!] no reading at pos={pos}")

        rows.append(row)
        pct = int((i + 1) / total * 40)
        bar = "█" * pct + "░" * (40 - pct)
        f6 = row.get("f6", 0)
        print(f"  [{bar}] {i+1:4d}/{total} pos={pos:7d}  590nm={f6}", end="\r")

    print()  # newline after progress bar

    # Turn LED off when done
    bus.send("LED_OFF")
    bus.expect(lambda l: l == "ACK LED_OFF", timeout=2.0, description="ACK LED_OFF")

    return rows


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {len(rows)} readings → {path}")


def plot_sweep(rows: list[dict], title: str) -> None:
    if not rows:
        print("No data to plot.")
        return

    positions = [r["pos"] for r in rows]
    f6  = [r.get("f6",  0) for r in rows]
    f7  = [r.get("f7",  0) for r in rows]
    clr = [r.get("clear", 0) for r in rows]

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#181825")

    ax.plot(positions, f6,  color="#ef9f76", lw=1.5, label="590 nm (f6)")
    ax.fill_between(positions, f6,  color="#ef9f76", alpha=0.08)
    ax.plot(positions, f7,  color="#ea999c", lw=1.5, label="630 nm (f7)")
    ax.fill_between(positions, f7,  color="#ea999c", alpha=0.08)
    ax.plot(positions, clr, color="#a6d189", lw=1.2, label="Clear",
            linestyle="--")

    ax.set_xlabel("Motor position (steps)", color="#cdd6f4", fontsize=10)
    ax.set_ylabel("Counts", color="#cdd6f4", fontsize=10)
    ax.set_title(title, color="#cdd6f4", fontsize=11)
    ax.tick_params(colors="#6c7086", labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#313244")
    ax.grid(True, color="#313244", lw=0.4, alpha=0.6)
    ax.legend(fontsize=9, facecolor="#1e1e2e", labelcolor="#cdd6f4",
              framealpha=0.8)

    # Interactive click: print position of clicked point
    def on_click(event):
        if event.inaxes:
            print(f"  clicked → pos ≈ {int(event.xdata):,} steps")
    fig.canvas.mpl_connect("button_press_event", on_click)

    plt.tight_layout()
    plt.show()


def print_summary(rows: list[dict]) -> None:
    if not rows:
        return
    print("\nSweep summary (top 10 by 590 nm):")
    print(f"  {'pos':>8}  {'590nm':>7}  {'630nm':>7}  {'clear':>7}")
    top = sorted(rows, key=lambda r: r.get("f6", 0), reverse=True)[:10]
    for r in sorted(top, key=lambda r: r["pos"]):
        print(f"  {r['pos']:>8}  {r.get('f6',0):>7}  {r.get('f7',0):>7}  {r.get('clear',0):>7}")
    print()
    print("Tip: well centres typically appear as peaks in 590 nm or clear channel.")
    print("     Click the plot to print the exact position at any point.")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="BioPayload well-position calibration sweep"
    )
    ap.add_argument("--port",      default=None)
    ap.add_argument("--baud",      type=int, default=DEFAULT_BAUD)
    ap.add_argument("--step",      type=int, default=500,
                    help="steps between readings (default 500)")
    ap.add_argument("--start",     type=int, default=None,
                    help="start position in steps (default: -(post-home-steps))")
    ap.add_argument("--end",       type=int, default=180000,
                    help="end position in steps (default 180000)")
    ap.add_argument("--post-home-steps", type=int, default=9600,
                    dest="post_home_steps",
                    help="must match setPostHomeSteps() in components.cpp (default 9600)")
    ap.add_argument("--fine",      type=int, nargs=2, metavar=("FROM", "TO"),
                    help="fine-sweep range; uses --step/4 if not also specified")
    ap.add_argument("--no-home",   action="store_true",
                    help="skip homing; sweep from current MOT_POS")
    ap.add_argument("--out",       default=None,
                    help="output CSV path (default: sweep_<timestamp>.csv)")
    ap.add_argument("--led",       type=int, nargs=3, default=[128, 128, 128],
                    metavar=("R","G","B"),
                    help="LED levels during sweep (default: 128 128 128 white)")
    ap.add_argument("--boot-wait", type=float, default=2.5, dest="boot_wait")
    args = ap.parse_args()

    port = args.port or auto_port()
    print(f"Opening {port} @ {args.baud}")
    bus = SerialBus(port, args.baud)

    try:
        if args.boot_wait > 0:
            time.sleep(args.boot_wait)
        for line in bus.read_lines(0.5):
            print(f"  [boot] {line}")

        bus.send("ABORT")
        bus.read_lines(0.5)

        if not args.no_home:
            home_motor(bus)

        # After homing the firmware backs up post_home_steps from the limit
        # switch before zeroing, so the limit switch is at -post_home_steps in
        # firmware coordinates.  Default the sweep start to that physical edge
        # so the full reachable range is covered.
        # Coordinate reference:
        #   limit switch closes  →  motor backs up post_home_steps  →  position 0
        #   so the switch is at position -(post_home_steps) = -9600 (default)
        #   and position 0 is the calibrated home, 9600 steps forward of the switch.
        #   Wells are at positive positions from 0; sweep starts there.
        if args.start is not None:
            start = args.start
        elif args.no_home:
            start = get_pos(bus)
        else:
            start = 0  # calibrated home (post_home_steps past the switch)

        print(f"post-home offset: {args.post_home_steps} steps  "
              f"(limit switch closes at position -{args.post_home_steps}; "
              f"position 0 = calibrated home)")
        positions = list(range(start, args.end + 1, args.step))
        if not positions or positions[-1] < args.end:
            positions.append(args.end)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.out) if args.out else Path(f"sweep_{timestamp}.csv")

        # Coarse sweep
        print(f"\nCoarse sweep: {start} → {args.end}, step={args.step}, "
              f"LED={args.led}, n={len(positions)} points"
              f"\n  (position 0 = {args.post_home_steps} steps from limit switch)")
        rows = run_sweep(bus, positions, tuple(args.led))
        save_csv(rows, out_path)
        print_summary(rows)

        # Optional fine sweep
        fine_rows = []
        if args.fine:
            f_from, f_to = args.fine
            fine_step = max(1, args.step // 4)
            fine_positions = list(range(f_from, f_to + 1, fine_step))
            print(f"\nFine sweep: {f_from} → {f_to}, step={fine_step}, "
                  f"n={len(fine_positions)} points")
            fine_rows = run_sweep(bus, fine_positions, tuple(args.led))
            fine_out = out_path.with_name(out_path.stem + "_fine.csv")
            save_csv(fine_rows, fine_out)
            print_summary(fine_rows)

        # Return motor to home after sweep
        print("Returning to position 0 …", end=" ", flush=True)
        current = get_pos(bus)
        move_to(bus, 0, current, timeout=120.0)
        print("done.")

        # Plot
        plot_sweep(rows, f"Coarse sweep (step={args.step})")
        if fine_rows:
            plot_sweep(fine_rows, f"Fine sweep {args.fine[0]}–{args.fine[1]} (step={fine_step})")

        return 0

    finally:
        try:
            bus.send("ABORT")
            time.sleep(0.2)
        except Exception:
            pass
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
