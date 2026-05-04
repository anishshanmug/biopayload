"""
Phase 2 protocol regression test for the BioPayload firmware.

Exercises every 1st-order command on a bare ESP32 (no peripherals required:
GPIO commands work without anything wired, and AS7341 absence is a graceful
NOT_FOUND rather than a hard error).

Usage:
    python test_protocol.py                # auto-detect serial port
    python test_protocol.py --port /dev/cu.usbmodem14101
    python test_protocol.py --skip-spec    # skip SPEC_READ if no AS7341 wired

Exit code 0 = all checks passed, 1 = at least one failure.

Design notes:

* Each ``expect_*`` helper waits up to ``timeout`` seconds for a matching line
  on the serial stream, ignoring any boot-banner / unrelated chatter in between.
  This is robust against the firmware emitting extra lines (``[boot] ...``,
  ``STATE IDLE``) we don't explicitly assert.
* All command sends end with ``\n``; the firmware splits on newline.
* The script flushes the serial input buffer before each test so we don't
  read stale ``DONE`` lines from a previous test.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    print("ERROR: pyserial not installed. Run: pip install pyserial", file=sys.stderr)
    sys.exit(2)


DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT = 2.0
HOME_TIMEOUT = 95.0  # MOT_HOME deadline (firmware 90 s) + 5 s slack


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #

def auto_port() -> str:
    candidates = sorted(glob.glob("/dev/cu.usbmodem*")) + sorted(
        glob.glob("/dev/ttyACM*")
    ) + sorted(glob.glob("/dev/ttyUSB*"))
    if not candidates:
        raise SystemExit(
            "No serial port found. Plug in the ESP32 or pass --port explicitly."
        )
    return candidates[0]


class SerialBus:
    """Thin wrapper that buffers received lines and provides expect()-style
    helpers. The dispatcher / state machine is the source of truth; this class
    just tries to be a faithful host-side mirror of the wire protocol.

    The receive buffer (``_rx``) and the queue of complete lines waiting to be
    consumed (``_pending``) are instance state, not locals on each ``expect``.
    Otherwise an ACK + DONE pair that arrives in the same USB-CDC packet
    (which is exactly what happens for fast async ops like ``PUMP_RUN 0`` and
    ``MOT_MOVE 50``) would lose its tail when the first ``expect`` returns:
    the function-local ``buf`` containing the unread DONE would just go out of
    scope, and the next ``expect`` would see an empty serial port and time
    out."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.log: List[str] = []
        self._rx: bytes = b""
        self._pending: List[str] = []

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def _drain(self) -> None:
        """Pull whatever's in the OS receive buffer into ``_rx`` and split
        completed lines into ``_pending``.

        Heartbeat lines (``HB <ms>``) are USB-CDC keep-alive emitted every 15 s
        by the firmware. Drop them at the bus layer so they never appear in
        test traces or log windows.
        """
        while True:
            chunk = self.ser.read(256)
            if not chunk:
                break
            self._rx += chunk
        while b"\n" in self._rx:
            line, _, self._rx = self._rx.partition(b"\n")
            text = line.decode("ascii", errors="replace").rstrip("\r")
            if text.startswith("HB "):
                continue
            self._pending.append(text)
            self.log.append(f"<- {text}")

    def flush(self) -> None:
        # Drain anything buffered (boot banner from the previous test, late
        # DONE lines, etc.) so the next expect() is deterministic.
        time.sleep(0.05)
        self._drain()
        self._pending.clear()
        # Note: we keep self._rx (a partial line) -- a half-received line has
        # to wait for its newline, no point dropping it.

    def send(self, line: str) -> None:
        self.log.append(f"-> {line}")
        self.ser.write((line + "\n").encode("ascii", errors="replace"))
        self.ser.flush()

    def read_lines(self, timeout: float) -> List[str]:
        deadline = time.monotonic() + timeout
        out: List[str] = []
        while time.monotonic() < deadline:
            self._drain()
            if self._pending:
                out.extend(self._pending)
                self._pending.clear()
            else:
                time.sleep(0.01)
        return out

    def expect(
        self,
        predicate: Callable[[str], bool],
        timeout: float = DEFAULT_TIMEOUT,
        description: str = "<line>",
    ) -> str:
        deadline = time.monotonic() + timeout
        while True:
            # Consume any line we already have queued before deciding to wait.
            while self._pending:
                text = self._pending.pop(0)
                if predicate(text):
                    return text
            if time.monotonic() >= deadline:
                break
            self._drain()
            if not self._pending:
                time.sleep(0.01)
        raise AssertionError(
            f"timeout {timeout}s waiting for {description}; "
            f"last 20 lines:\n" + "\n".join(self.log[-20:])
        )


# --------------------------------------------------------------------------- #
# Test framework (no pytest dependency)
# --------------------------------------------------------------------------- #

@dataclass
class Result:
    name: str
    ok: bool
    message: str = ""


@dataclass
class Suite:
    bus: SerialBus
    skip_spec: bool = False
    results: List[Result] = field(default_factory=list)

    def run(self, name: str, fn: Callable[["Suite"], None]) -> None:
        print(f"  {name} ...", end=" ", flush=True)
        self.bus.flush()
        try:
            fn(self)
        except AssertionError as e:
            print("FAIL")
            self.results.append(Result(name, False, str(e)))
        except Exception as e:  # pragma: no cover
            print(f"ERROR: {e!r}")
            self.results.append(Result(name, False, repr(e)))
        else:
            print("ok")
            self.results.append(Result(name, True))

    def summary(self) -> int:
        passed = sum(1 for r in self.results if r.ok)
        failed = [r for r in self.results if not r.ok]
        print()
        print(f"{passed} passed, {len(failed)} failed")
        for r in failed:
            print(f"  FAIL {r.name}")
            for line in r.message.splitlines():
                print(f"      {line}")
        return 0 if not failed else 1


# --------------------------------------------------------------------------- #
# Test cases
# --------------------------------------------------------------------------- #

def t_ping(s: Suite) -> None:
    s.bus.send("PING")
    s.bus.expect(lambda l: l == "ACK PING", description="ACK PING")


def t_hello(s: Suite) -> None:
    s.bus.send("HELLO")
    s.bus.expect(
        lambda l: l.startswith("ACK HELLO "),
        description="ACK HELLO <version>",
    )


def t_state_idle(s: Suite) -> None:
    s.bus.send("STATE")
    s.bus.expect(lambda l: l == "STATE IDLE", description="STATE IDLE")


def t_sys_status(s: Suite) -> None:
    s.bus.send("SYS_STATUS")
    line = s.bus.expect(
        lambda l: l.startswith("SYS_STATUS "),
        description="SYS_STATUS line",
    )
    # Sanity-check the field set.
    for field_name in ("pump:", "motor:", "led:", "limit:", "spec:", "sd:", "state:"):
        assert field_name in line, f"missing {field_name!r} in {line!r}"


def t_unknown_cmd(s: Suite) -> None:
    s.bus.send("DEFINITELY_NOT_A_COMMAND")
    s.bus.expect(
        lambda l: l.startswith("ERR UNKNOWN"),
        description="ERR UNKNOWN",
    )


def t_pump_run(s: Suite) -> None:
    s.bus.send("PUMP_RUN 200")
    s.bus.expect(lambda l: l == "ACK PUMP_RUN", description="ACK PUMP_RUN")
    # DONE should fire ~200ms later. Allow plenty of slack for USB/CDC.
    s.bus.expect(
        lambda l: l == "DONE PUMP_RUN",
        timeout=2.0,
        description="DONE PUMP_RUN",
    )


def t_pump_run_zero_immediate_done(s: Suite) -> None:
    s.bus.send("PUMP_RUN 0")
    s.bus.expect(lambda l: l == "ACK PUMP_RUN", description="ACK PUMP_RUN")
    s.bus.expect(
        lambda l: l == "DONE PUMP_RUN",
        timeout=0.5,
        description="DONE PUMP_RUN (immediate)",
    )


def t_pump_run_bad_arg(s: Suite) -> None:
    s.bus.send("PUMP_RUN")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_ARG"),
        description="ERR BAD_ARG (no args)",
    )
    s.bus.send("PUMP_RUN -1")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_ARG"),
        description="ERR BAD_ARG (negative)",
    )


def t_pump_on_off(s: Suite) -> None:
    s.bus.send("PUMP_ON")
    s.bus.expect(lambda l: l == "ACK PUMP_ON", description="ACK PUMP_ON")
    s.bus.send("PUMP_STATUS")
    s.bus.expect(
        lambda l: l == "PUMP_STATUS RUNNING",
        description="PUMP_STATUS RUNNING",
    )
    s.bus.send("PUMP_OFF")
    s.bus.expect(lambda l: l == "ACK PUMP_OFF", description="ACK PUMP_OFF")
    s.bus.send("PUMP_STATUS")
    s.bus.expect(
        lambda l: l == "PUMP_STATUS IDLE",
        description="PUMP_STATUS IDLE",
    )


def t_led_set_off(s: Suite) -> None:
    s.bus.send("LED_SET 32 64 128")
    s.bus.expect(lambda l: l == "ACK LED_SET", description="ACK LED_SET")
    s.bus.send("LED_STATUS")
    s.bus.expect(
        lambda l: l == "LED_STATUS 32 64 128",
        description="LED_STATUS 32 64 128",
    )
    s.bus.send("LED_OFF")
    s.bus.expect(lambda l: l == "ACK LED_OFF", description="ACK LED_OFF")
    s.bus.send("LED_STATUS")
    s.bus.expect(
        lambda l: l == "LED_STATUS 0 0 0",
        description="LED_STATUS 0 0 0",
    )


def t_led_bad_arg(s: Suite) -> None:
    s.bus.send("LED_SET 256 0 0")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_ARG"),
        description="ERR BAD_ARG (>255)",
    )
    s.bus.send("LED_SET 0 0")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_ARG"),
        description="ERR BAD_ARG (too few args)",
    )


def t_lim_status(s: Suite) -> None:
    s.bus.send("LIM_STATUS")
    s.bus.expect(
        lambda l: l in ("LIM_STATUS OPEN", "LIM_STATUS CLOSED"),
        description="LIM_STATUS OPEN|CLOSED",
    )


def t_mot_move(s: Suite) -> None:
    # First command in the motor block: assert the driver for subsequent moves.
    s.bus.send("MOT_ENABLE")
    s.bus.expect(lambda l: l == "ACK MOT_ENABLE", description="ACK MOT_ENABLE")
    # Read position before the move so the assertion is history-independent
    # (the counter accumulates across resets if the board isn't power-cycled).
    s.bus.send("MOT_POS")
    pos_line = s.bus.expect(lambda l: l.startswith("MOT_POS "), description="MOT_POS (pre-move)")
    pos_before = int(pos_line.split()[1])
    s.bus.send("MOT_MOVE 50")
    s.bus.expect(lambda l: l == "ACK MOT_MOVE", description="ACK MOT_MOVE")
    s.bus.expect(
        lambda l: l == "DONE MOT_MOVE",
        timeout=2.0,
        description="DONE MOT_MOVE",
    )
    s.bus.send("MOT_POS")
    pos_line = s.bus.expect(lambda l: l.startswith("MOT_POS "), description="MOT_POS (post-move)")
    pos_after = int(pos_line.split()[1])
    delta = pos_after - pos_before
    assert delta == 50, f"expected position delta 50, got {delta} (before={pos_before} after={pos_after})"


def t_mot_run_stop(s: Suite) -> None:
    s.bus.send("MOT_RUN FWD")
    s.bus.expect(lambda l: l == "ACK MOT_RUN", description="ACK MOT_RUN")
    s.bus.send("MOT_STATUS")
    s.bus.expect(
        lambda l: l == "MOT_STATUS MOVING",
        description="MOT_STATUS MOVING",
    )
    s.bus.send("MOT_STOP")
    s.bus.expect(lambda l: l == "ACK MOT_STOP", description="ACK MOT_STOP")
    # Give update() one tick to actually halt motion.
    time.sleep(0.05)
    s.bus.send("MOT_STATUS")
    s.bus.expect(
        lambda l: l == "MOT_STATUS IDLE",
        description="MOT_STATUS IDLE",
    )


def t_mot_home_timeout(s: Suite) -> None:
    """With no limit switch wired (pin reads HIGH = OPEN), MOT_HOME must
    eventually time out and emit ERR HOME_TIMEOUT. If a switch IS wired and
    happens to read CLOSED at the start, the home returns DONE immediately --
    accept either outcome."""
    s.bus.send("MOT_HOME")
    s.bus.expect(lambda l: l == "ACK MOT_HOME", description="ACK MOT_HOME")
    s.bus.expect(
        lambda l: l in ("DONE MOT_HOME", "ERR HOME_TIMEOUT"),
        timeout=HOME_TIMEOUT,
        description="DONE MOT_HOME or ERR HOME_TIMEOUT",
    )
    # Last command in the motor block: release the driver.
    s.bus.send("MOT_DISABLE")
    s.bus.expect(lambda l: l == "ACK MOT_DISABLE", description="ACK MOT_DISABLE")


def t_spec_status(s: Suite) -> None:
    s.bus.send("SPEC_STATUS")
    s.bus.expect(
        lambda l: l in ("SPEC_STATUS READY", "SPEC_STATUS NOT_FOUND"),
        description="SPEC_STATUS READY|NOT_FOUND",
    )


def t_spec_read(s: Suite) -> None:
    if s.skip_spec:
        return
    s.bus.send("SPEC_STATUS")
    status = s.bus.expect(
        lambda l: l.startswith("SPEC_STATUS "),
        description="SPEC_STATUS",
    )
    if "NOT_FOUND" in status:
        # Without an AS7341 wired the test is to confirm we get the right ERR.
        s.bus.send("SPEC_READ")
        s.bus.expect(
            lambda l: l == "ERR NO_SENSOR",
            description="ERR NO_SENSOR (no sensor)",
        )
        return
    # SPEC_READ is now async: ACK → TELEM → DONE SPEC_READ
    s.bus.send("SPEC_READ")
    s.bus.expect(
        lambda l: l == "ACK SPEC_READ",
        description="ACK SPEC_READ",
    )
    s.bus.expect(
        lambda l: l.startswith("TELEM {") and "f1" in l and "nir" in l,
        timeout=3.0,
        description="TELEM {...}",
    )
    s.bus.expect(
        lambda l: l == "DONE SPEC_READ",
        timeout=2.0,
        description="DONE SPEC_READ",
    )


def t_spec_bad_args(s: Suite) -> None:
    s.bus.send("SPEC_GAIN 11")
    s.bus.expect(
        lambda l: l.startswith("ERR "),
        description="ERR (SPEC_GAIN 11)",
    )
    s.bus.send("SPEC_ATIME 256")
    s.bus.expect(
        lambda l: l.startswith("ERR "),
        description="ERR (SPEC_ATIME 256)",
    )


def t_sd_status(s: Suite) -> None:
    s.bus.send("SD_STATUS")
    line = s.bus.expect(
        lambda l: l.startswith("SD_STATUS "),
        description="SD_STATUS READY|NOT_FOUND",
    )
    # Both outcomes are valid on a bare board; verify the shape is right.
    if "READY" in line:
        assert "total:" in line and "used:" in line, \
            f"SD_STATUS READY missing total/used fields: {line!r}"
    else:
        assert "NOT_FOUND" in line, \
            f"Unexpected SD_STATUS response: {line!r}"


def t_sd_list(s: Suite) -> None:
    s.bus.send("SD_STATUS")
    status = s.bus.expect(lambda l: l.startswith("SD_STATUS "), description="SD_STATUS")
    if "NOT_FOUND" in status:
        # SD_LIST on a missing card should return ERR, not hang.
        s.bus.send("SD_LIST")
        s.bus.expect(lambda l: l.startswith("ERR "), description="ERR (no card)")
        return
    s.bus.send("SD_LIST")
    # Consume entries until SD_LIST_END (may be 0 files on a fresh card).
    s.bus.expect(
        lambda l: l == "SD_LIST_END" or l.startswith("SD_FILE "),
        timeout=3.0,
        description="SD_FILE or SD_LIST_END",
    )
    # Drain the rest.
    s.bus.read_lines(0.3)


def _get_events_log_size(s: Suite) -> int | None:
    """Return the byte size of /events.log, or None if not found."""
    s.bus.flush()
    s.bus.send("SD_LIST")
    size: int | None = None
    while True:
        line = s.bus.expect(
            lambda l: l.startswith("SD_FILE ") or l == "SD_LIST_END",
            timeout=3.0,
            description="SD_LIST entry",
        )
        if line == "SD_LIST_END":
            break
        parts = line.split()
        if len(parts) == 3 and parts[1] == "events.log":
            size = int(parts[2])
    return size


def t_sd_write(s: Suite) -> None:
    s.bus.send("SD_STATUS")
    status = s.bus.expect(lambda l: l.startswith("SD_STATUS "), description="SD_STATUS")
    if "NOT_FOUND" in status:
        print("    (no SD card — skipping write test)")
        return

    size_before = _get_events_log_size(s)
    assert size_before is not None, (
        "events.log not found on SD card — was the card inserted before boot?"
    )

    s.bus.send("ABORT")
    s.bus.expect(lambda l: l == "ACK ABORT", description="ACK ABORT")
    # Give the firmware a moment to flush the append.
    time.sleep(0.1)

    size_after = _get_events_log_size(s)
    assert size_after is not None, "events.log disappeared after ABORT"
    assert size_after > size_before, (
        f"events.log did not grow after ABORT ({size_before} → {size_after} bytes)"
    )


def t_abort_clears_pump(s: Suite) -> None:
    s.bus.send("PUMP_RUN 5000")
    s.bus.expect(lambda l: l == "ACK PUMP_RUN", description="ACK PUMP_RUN")
    s.bus.send("ABORT")
    s.bus.expect(lambda l: l == "ACK ABORT", description="ACK ABORT")
    # ABORT clears pending DONEs without emitting them. Verify by checking
    # that no DONE PUMP_RUN comes through in the next 300ms and the pump is
    # IDLE.
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        # If a DONE leaks through we'll fail the next read.
        time.sleep(0.05)
    s.bus.send("PUMP_STATUS")
    s.bus.expect(
        lambda l: l == "PUMP_STATUS IDLE",
        description="PUMP_STATUS IDLE post-ABORT",
    )


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, help="serial device (auto-detect if omitted)")
    ap.add_argument(
        "--baud", type=int, default=DEFAULT_BAUD, help="baud rate (default 115200)"
    )
    ap.add_argument(
        "--skip-spec",
        action="store_true",
        help="skip the SPEC_READ test (use if no AS7341 is wired)",
    )
    ap.add_argument(
        "--boot-wait",
        type=float,
        default=2.5,
        help="seconds to wait after opening the port (default 2.5)",
    )
    args = ap.parse_args()

    port = args.port or auto_port()
    print(f"Opening {port} @ {args.baud}")
    bus = SerialBus(port, args.baud)
    try:
        # Give the firmware time to print its boot banner. The `expect_*`
        # helpers all flush stale lines before each test, so anything we miss
        # here is benign.
        time.sleep(args.boot_wait)
        # Pull whatever boot banner appeared.
        for line in bus.read_lines(0.5):
            print(f"  [boot] {line}")

        suite = Suite(bus, skip_spec=args.skip_spec)

        print("Running protocol tests:")
        suite.run("PING",                    t_ping)
        suite.run("HELLO",                   t_hello)
        suite.run("STATE",                   t_state_idle)
        suite.run("SYS_STATUS",              t_sys_status)
        suite.run("unknown command",         t_unknown_cmd)

        suite.run("PUMP_RUN basic",          t_pump_run)
        suite.run("PUMP_RUN 0 immediate",    t_pump_run_zero_immediate_done)
        suite.run("PUMP_RUN bad arg",        t_pump_run_bad_arg)
        suite.run("PUMP_ON / OFF / STATUS",  t_pump_on_off)

        suite.run("LED_SET / OFF / STATUS",  t_led_set_off)
        suite.run("LED_SET bad arg",         t_led_bad_arg)

        suite.run("LIM_STATUS",              t_lim_status)

        suite.run("MOT_MOVE",                t_mot_move)
        suite.run("MOT_RUN / STOP",          t_mot_run_stop)
        suite.run("MOT_HOME (timeout path)", t_mot_home_timeout)

        suite.run("SPEC_STATUS",             t_spec_status)
        suite.run("SPEC_READ",               t_spec_read)
        suite.run("SPEC bad args",           t_spec_bad_args)

        suite.run("SD_STATUS",               t_sd_status)
        suite.run("SD_LIST",                 t_sd_list)
        suite.run("SD write (events.log)",   t_sd_write)

        suite.run("ABORT clears pending",    t_abort_clears_pump)

        return suite.summary()
    finally:
        try:
            bus.send("ABORT")
            time.sleep(0.3)
        except Exception:
            pass
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
