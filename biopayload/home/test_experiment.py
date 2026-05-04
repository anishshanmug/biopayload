"""
Phase 3 runtime/state-machine regression test for the BioPayload firmware.

Coverage:
  Config validation   — bad JSON, missing fields, out-of-range values,
                        too many wells, empty run_id
  State guards        — IDLE-only commands rejected during PRIMING/ACTIVE/SCANNING;
                        START rejected while a run is in progress
  Read-only commands  — PING, STATE, SYS_STATUS, PUMP_STATUS, MOT_POS,
                        MOT_INTERVAL all work during a live run
  ABORT paths         — during PRIMING, during ACTIVE, during SCANNING;
                        no hardware left running, no RESULT/DONE leaks
  Config persistence  — config survives ABORT; re-START without re-upload
  State transitions   — PRIMING → ACTIVE → SCANNING → ACTIVE → DONE → IDLE;
                        zero-duration ACTIVE skips straight to DONE
  Scheduled actions   — SCAN_ALL_WELLS, DISPENSE; no-scheduled-action path
  Hardware agnostic   — default configs avoid real motor travel by targeting
                        the current MOT_POS, use homing:false, and tolerate
                        absent sensors / SD card
  Sequential runs     — two runs back-to-back confirm timer/cursor reset
  Hardware-only paths — opt-in flags cover homing success and timeout later,
                        once the physical rig is ready

Resilience: each test is preceded by an automatic ABORT to guarantee the
firmware is in IDLE, so a failure in test N never cascades into test N+1.

No peripherals required for the default test suite. All bare-board caveats:
  - scan well targets  → generated from current MOT_POS so delta == 0
  - SPEC_READ          → zero-valued TELEM if AS7341 absent (NOT_FOUND path)
  - CLEAR_CONFIG       → makes START/NO_CONFIG deterministic without MCU reset

Usage:
    python test_experiment.py
    python test_experiment.py --port /dev/cu.usbmodem14101
    python test_experiment.py --boot-wait 0        # already running
    python test_experiment.py --hardware-homing-success
    python test_experiment.py --hardware-home-timeout

Exit code 0 = all checks passed, 1 = at least one failure.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import List

from test_protocol import SerialBus, Suite, auto_port, DEFAULT_BAUD


# --------------------------------------------------------------------------- #
# RuntimeSuite -- resilient subclass that recovers between tests
# --------------------------------------------------------------------------- #

class RuntimeSuite(Suite):
    """Suite that forces a known runtime baseline before every test.

    ABORT guarantees IDLE even if a previous test timed out mid-run.
    CLEAR_CONFIG guarantees no stored experiment config leaks across test
    cases, so the suite is standalone even if opening the serial port does not
    reboot the MCU.
    """

    def run(self, name, fn):
        self.bus.send("ABORT")
        self.bus.read_lines(0.3)
        self.bus.send("CLEAR_CONFIG")
        self.bus.expect(
            lambda l: l == "ACK CLEAR_CONFIG",
            timeout=1.0,
            description="ACK CLEAR_CONFIG (test setup)",
        )
        super().run(name, fn)


# --------------------------------------------------------------------------- #
# JSON config catalogue
# --------------------------------------------------------------------------- #

# Standard runtime smoke: 300 ms prime, 5 s active, scan every 2 s,
# 2 wells, no homing. Tests replace steps_from_home:0 with current MOT_POS.
SMOKE_CONFIG = (
    '{"run_id":"smoke","priming":{"pump_ms":300},'
    '"active":{"duration_ms":5000,"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":2000}]},'
    '"scanning":{"homing":false,"settle_ms":50,"led_off_after_read":true,'
    '"wells":['
    '{"row":0,"col":0,"steps_from_home":0,"led":[8,0,0]},'
    '{"row":0,"col":1,"steps_from_home":0,"led":[0,8,0]}'
    ']}}'
)

# Fast minimal: no prime, 500 ms active, no scheduled actions, no wells.
# Used for sequential-run and timing tests where speed matters.
FAST_CONFIG = (
    '{"run_id":"fast","priming":{"pump_ms":0},'
    '"active":{"duration_ms":500,"scheduled":[]},'
    '"scanning":{"homing":false,"settle_ms":0,"led_off_after_read":true,"wells":[]}}'
)

# Long active (30 s) for mid-ACTIVE abort and state-guard tests.
# Scan every 60 s so no scan fires during the test window.
LONG_ACTIVE_CONFIG = (
    '{"run_id":"long-active","priming":{"pump_ms":0},'
    '"active":{"duration_ms":30000,"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":60000}]},'
    '"scanning":{"homing":false,"settle_ms":0,"led_off_after_read":true,"wells":[]}}'
)

# Slow scan: 3 s settle per well -> ~6 s in SCANNING, plenty of time to ABORT.
# Tests replace steps_from_home:0 with current MOT_POS.
SLOW_SCAN_CONFIG = (
    '{"run_id":"slow-scan","priming":{"pump_ms":0},'
    '"active":{"duration_ms":30000,"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":1000}]},'
    '"scanning":{"homing":false,"settle_ms":3000,"led_off_after_read":true,'
    '"wells":['
    '{"row":0,"col":0,"steps_from_home":0,"led":[8,0,0]},'
    '{"row":0,"col":1,"steps_from_home":0,"led":[0,8,0]}'
    ']}}'
)

# Zero active duration: enterActive immediately calls enterDone, never emits STATE ACTIVE.
ZERO_ACTIVE_CONFIG = (
    '{"run_id":"zero-active","priming":{"pump_ms":0},'
    '"active":{"duration_ms":0,"scheduled":[]},'
    '"scanning":{"homing":false,"settle_ms":0,"led_off_after_read":true,"wells":[]}}'
)

# No scheduled actions: runs on pure duration timer, no scanning.
NO_SCHED_CONFIG = (
    '{"run_id":"no-sched","priming":{"pump_ms":200},'
    '"active":{"duration_ms":1500,"scheduled":[]},'
    '"scanning":{"homing":false,"settle_ms":0,"led_off_after_read":true,"wells":[]}}'
)

# Dispense + scan in the same run.
DISPENSE_CONFIG = (
    '{"run_id":"dispense-test","priming":{"pump_ms":0},'
    '"active":{"duration_ms":4000,'
    '"scheduled":['
    '{"cmd":"DISPENSE","every_ms":2000,"pump_ms":200},'
    '{"cmd":"SCAN_ALL_WELLS","every_ms":4500}'
    ']},'
    '"scanning":{"homing":false,"settle_ms":0,"led_off_after_read":true,"wells":[]}}'
)

# Homing:true — requires the limit switch to read CLOSED for homing to succeed.
# The test probes LIM_STATUS and skips if OPEN. When CLOSED, postHomeSteps=9333
# at 120 µs/step ≈ 1.1 s, then 1 well read, then back to ACTIVE.
HOMING_CONFIG = (
    '{"run_id":"homing-test","priming":{"pump_ms":0},'
    '"active":{"duration_ms":10000,"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":500}]},'
    '"scanning":{"homing":true,"settle_ms":0,"led_off_after_read":true,'
    '"wells":[{"row":0,"col":0,"steps_from_home":0,"led":[8,0,0]}]}}'
)

# Hardware-only: homing:true with NO limit switch wired (or held open), causes HOME_TIMEOUT
# and drives the SM into ERROR. Gate behind --hardware-home-timeout.
ERROR_TRIGGER_CONFIG = (
    '{"run_id":"error-trigger","priming":{"pump_ms":0},'
    '"active":{"duration_ms":60000,"scheduled":[{"cmd":"SCAN_ALL_WELLS","every_ms":500}]},'
    '"scanning":{"homing":true,"settle_ms":0,"led_off_after_read":true,'
    '"wells":[{"row":0,"col":0,"steps_from_home":0,"led":[8,0,0]}]}}'
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _abort_and_idle(s: Suite) -> None:
    """Convenience: send ABORT and wait for STATE IDLE. Used in test teardowns."""
    s.bus.send("ABORT")
    s.bus.expect(lambda l: l == "ACK ABORT",  description="ACK ABORT (teardown)")
    s.bus.expect(lambda l: l == "STATE IDLE", description="STATE IDLE (teardown)")


def _assert_no_leak(lines: List[str]) -> None:
    """Assert that a drained window contains no RESULT or STATE DONE."""
    for line in lines:
        assert not line.startswith("RESULT "), \
            f"unexpected RESULT after ABORT: {line!r}"
        assert line != "STATE DONE", \
            f"unexpected STATE DONE after ABORT: {line!r}"


def _assert_hardware_idle(s: Suite, context: str = "") -> None:
    """Verify SYS_STATUS shows pump/motor/state all IDLE."""
    s.bus.send("SYS_STATUS")
    status = s.bus.expect(
        lambda l: l.startswith("SYS_STATUS "),
        description=f"SYS_STATUS {context}",
    )
    assert "pump:IDLE"  in status, f"pump still running ({context}): {status!r}"
    assert "motor:IDLE" in status, f"motor still moving ({context}): {status!r}"
    assert "state:IDLE" in status, f"SM not IDLE ({context}): {status!r}"


def _current_motor_position(s: Suite) -> int:
    """Read the firmware's current motor position without assuming hardware state."""
    s.bus.send("MOT_POS")
    line = s.bus.expect(
        lambda l: l.startswith("MOT_POS "),
        description="MOT_POS",
    )
    return int(line.split()[1])


def _at_current_motor_position(s: Suite, config: str) -> str:
    """Make a scan config hardware-agnostic by avoiding real motor travel.

    Phase 3 tests care that SCANNING advances through MOVING -> SETTLING ->
    READING. They do not care whether the stage physically travels. Replacing
    zero-valued well targets with the current absolute MOT_POS makes each move
    delta zero, so the runtime behavior is exercised without requiring the
    stage to be homed or wired.
    """
    pos = _current_motor_position(s)
    return config.replace('"steps_from_home":0', f'"steps_from_home":{pos}')


# --------------------------------------------------------------------------- #
# 1. Config validation — error paths
#    RuntimeSuite clears config before each case, so NO_CONFIG is deterministic.
# --------------------------------------------------------------------------- #

def t_set_config_bad_json(s: Suite) -> None:
    s.bus.send("SET_CONFIG {this is not valid json")
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (bad JSON)",
    )
    assert "JSON" in line, f"expected JSON in field, got: {line!r}"


def t_set_config_missing_runid(s: Suite) -> None:
    s.bus.send('SET_CONFIG {}')
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (missing run_id)",
    )
    assert "RUN_ID" in line, f"expected RUN_ID in field, got: {line!r}"


def t_set_config_empty_runid(s: Suite) -> None:
    s.bus.send('SET_CONFIG {"run_id":""}')
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (empty run_id)",
    )
    assert "RUN_ID" in line, f"expected RUN_ID in field, got: {line!r}"


def t_set_config_bad_led(s: Suite) -> None:
    bad = (
        '{"run_id":"x","priming":{"pump_ms":0},'
        '"active":{"duration_ms":0,"scheduled":[]},'
        '"scanning":{"homing":false,"settle_ms":0,'
        '"wells":[{"row":0,"col":0,"steps_from_home":0,"led":[300,0,0]}]}}'
    )
    s.bus.send("SET_CONFIG " + bad)
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (LED 300 out of range)",
    )
    assert "LED" in line, f"expected LED in field, got: {line!r}"


def t_set_config_too_many_wells(s: Suite) -> None:
    # 13 wells exceeds EXPERIMENT_MAX_WELLS = 12.
    wells = ",".join(
        '{"row":0,"col":%d,"steps_from_home":0,"led":[0,0,0]}' % i
        for i in range(13)
    )
    bad = (
        '{"run_id":"toomany","priming":{"pump_ms":0},'
        '"active":{"duration_ms":0,"scheduled":[]},'
        f'"scanning":{{"homing":false,"settle_ms":0,"wells":[{wells}]}}}}'
    )
    s.bus.send("SET_CONFIG " + bad)
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (13 wells > max 12)",
    )
    assert "WELL" in line, f"expected WELL in field, got: {line!r}"


def t_set_config_missing_active(s: Suite) -> None:
    bad = '{"run_id":"no-active","priming":{"pump_ms":0}}'
    s.bus.send("SET_CONFIG " + bad)
    line = s.bus.expect(
        lambda l: l.startswith("ERR BAD_CONFIG"),
        description="ERR BAD_CONFIG (missing active block)",
    )
    assert "ACTIVE" in line, f"expected ACTIVE in field, got: {line!r}"


def t_start_no_config(s: Suite) -> None:
    s.bus.send("START")
    s.bus.expect(
        lambda l: l == "ERR NO_CONFIG",
        description="ERR NO_CONFIG",
    )


# --------------------------------------------------------------------------- #
# 2. Full smoke run
# --------------------------------------------------------------------------- #

def t_phase3_smoke(s: Suite) -> None:
    """PRIMING → ACTIVE → SCANNING (2 wells) → ACTIVE → DONE → IDLE."""
    s.bus.send("SET_CONFIG " + _at_current_motor_position(s, SMOKE_CONFIG))
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE (after PRIMING)",
    )
    s.bus.expect(
        lambda l: l == "STATE SCANNING",
        timeout=4.0, description="STATE SCANNING (1st)",
    )
    for i in range(2):
        line = s.bus.expect(
            lambda l: l.startswith("TELEM ") and '"event":"well"' in l,
            timeout=4.0, description=f"TELEM well[{i}]",
        )
        assert f'"col":{i}' in line, f"well column order wrong: {line!r}"
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE (after 1st scan)",
    )
    s.bus.expect(
        lambda l: l == "STATE DONE",
        timeout=14.0, description="STATE DONE",
    )
    result = s.bus.expect(
        lambda l: l.startswith("RESULT "),
        timeout=2.0, description="RESULT",
    )
    assert '"run_id":"smoke"' in result, f"RESULT missing run_id: {result!r}"
    assert '"status":"OK"'    in result, f"RESULT not OK: {result!r}"
    assert '"scans":'         in result, f"RESULT missing scans: {result!r}"
    assert '"wells":'         in result, f"RESULT missing wells: {result!r}"
    assert '"duration_ms":'   in result, f"RESULT missing duration: {result!r}"
    s.bus.expect(
        lambda l: l == "STATE IDLE",
        timeout=2.0, description="STATE IDLE (post-DONE)",
    )


# --------------------------------------------------------------------------- #
# 3. ABORT paths
# --------------------------------------------------------------------------- #

def t_abort_during_priming(s: Suite) -> None:
    """ABORT during PRIMING: hardware idle, no RESULT/DONE leaks."""
    # Use SMOKE_CONFIG (300 ms prime) so PRIMING lasts long enough to ABORT.
    s.bus.send("SET_CONFIG " + SMOKE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")

    _abort_and_idle(s)
    _assert_no_leak(s.bus.read_lines(0.5))
    _assert_hardware_idle(s, "after abort during PRIMING")


def t_abort_during_active(s: Suite) -> None:
    """ABORT during ACTIVE: hardware idle, no RESULT/DONE leaks."""
    s.bus.send("SET_CONFIG " + LONG_ACTIVE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    # pump_ms=0 → PRIMING is announced but immediately transitions to ACTIVE.
    s.bus.expect(
        lambda l: l in ("STATE PRIMING", "STATE ACTIVE"),
        timeout=2.0, description="STATE PRIMING|ACTIVE",
    )
    # Ensure we are in ACTIVE (consume one more event if we only saw PRIMING).
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE",
    )

    _abort_and_idle(s)
    _assert_no_leak(s.bus.read_lines(0.5))
    _assert_hardware_idle(s, "after abort during ACTIVE")


def t_abort_during_scanning(s: Suite) -> None:
    """ABORT while SCANNING (settle window): motor/LED/pump left idle, no RESULT."""
    s.bus.send("SET_CONFIG " + _at_current_motor_position(s, SLOW_SCAN_CONFIG))
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",      description="ACK START")
    # pump_ms=0 → bounces straight into ACTIVE after STATE PRIMING.
    s.bus.expect(
        lambda l: l in ("STATE PRIMING", "STATE ACTIVE"),
        timeout=2.0, description="STATE PRIMING|ACTIVE",
    )
    # SCAN_ALL_WELLS fires every 1 s; settle_ms:3000 → SCANNING lasts ~6 s.
    s.bus.expect(
        lambda l: l == "STATE SCANNING",
        timeout=5.0, description="STATE SCANNING",
    )

    # We're now inside SCANNING with ~6 s of settle time remaining.
    _abort_and_idle(s)
    _assert_no_leak(s.bus.read_lines(0.5))
    _assert_hardware_idle(s, "after abort during SCANNING")


# --------------------------------------------------------------------------- #
# 4. State-guard enforcement
# --------------------------------------------------------------------------- #

def t_start_rejected_during_run(s: Suite) -> None:
    """START while not IDLE must return ERR BAD_STATE."""
    s.bus.send("SET_CONFIG " + LONG_ACTIVE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START", description="ACK START")
    s.bus.expect(
        lambda l: l in ("STATE PRIMING", "STATE ACTIVE"),
        timeout=2.0, description="in PRIMING|ACTIVE",
    )

    s.bus.send("START")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_STATE"),
        description="ERR BAD_STATE (START while running)",
    )
    _abort_and_idle(s)


def t_idle_cmds_rejected_during_run(s: Suite) -> None:
    """PUMP_RUN, PUMP_ON, MOT_MOVE, LED_SET all refused while ACTIVE."""
    s.bus.send("SET_CONFIG " + LONG_ACTIVE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START", description="ACK START")
    # Consume until we're in ACTIVE (pump_ms=0 → fast transition).
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=3.0, description="STATE ACTIVE",
    )

    idle_only_cmds = [
        ("PUMP_RUN 500",     "PUMP_RUN"),
        ("PUMP_ON",          "PUMP_ON"),
        ("MOT_MOVE 10",      "MOT_MOVE"),
        ("LED_SET 255 0 0",  "LED_SET"),
        ("SET_CONFIG " + FAST_CONFIG, "SET_CONFIG"),
    ]
    for cmd, label in idle_only_cmds:
        s.bus.send(cmd)
        line = s.bus.expect(
            lambda l: l.startswith("ERR BAD_STATE"),
            description=f"ERR BAD_STATE ({label} during ACTIVE)",
        )
        assert "BAD_STATE" in line, f"{label}: expected BAD_STATE, got: {line!r}"

    _abort_and_idle(s)


def t_readonly_cmds_during_run(s: Suite) -> None:
    """MASK_ALL commands (PING, STATE, PUMP_STATUS, MOT_POS, MOT_INTERVAL) work during ACTIVE."""
    s.bus.send("SET_CONFIG " + LONG_ACTIVE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START", description="ACK START")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=3.0, description="STATE ACTIVE",
    )

    # PING — always-on heartbeat.
    s.bus.send("PING")
    s.bus.expect(lambda l: l == "ACK PING", description="ACK PING during ACTIVE")

    # STATE — must report current state.
    s.bus.send("STATE")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        description="STATE ACTIVE (STATE cmd during ACTIVE)",
    )

    # SYS_STATUS — must report state:ACTIVE.
    s.bus.send("SYS_STATUS")
    status = s.bus.expect(
        lambda l: l.startswith("SYS_STATUS "),
        description="SYS_STATUS during ACTIVE",
    )
    assert "state:ACTIVE" in status, f"SYS_STATUS did not report ACTIVE: {status!r}"

    # PUMP_STATUS — pump is not running in this config.
    s.bus.send("PUMP_STATUS")
    s.bus.expect(
        lambda l: l == "PUMP_STATUS IDLE",
        description="PUMP_STATUS IDLE during ACTIVE",
    )

    # MOT_POS — returns a number (any value is valid on a bare board).
    s.bus.send("MOT_POS")
    line = s.bus.expect(
        lambda l: l.startswith("MOT_POS "),
        description="MOT_POS during ACTIVE",
    )
    pos_str = line.split()[1]
    int(pos_str)  # assert it's numeric; raises ValueError if not

    # MOT_INTERVAL — MASK_ALL write command, changes motor speed mid-run.
    s.bus.send("MOT_INTERVAL 200")
    s.bus.expect(
        lambda l: l == "ACK MOT_INTERVAL",
        description="ACK MOT_INTERVAL during ACTIVE",
    )
    # Restore default.
    s.bus.send("MOT_INTERVAL 120")
    s.bus.expect(
        lambda l: l == "ACK MOT_INTERVAL",
        description="ACK MOT_INTERVAL restore",
    )

    _abort_and_idle(s)


def t_set_config_rejected_during_run(s: Suite) -> None:
    """SET_CONFIG is IDLE-only: rejected during PRIMING or ACTIVE."""
    s.bus.send("SET_CONFIG " + SMOKE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")
    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START", description="ACK START")
    s.bus.expect(
        lambda l: l in ("STATE PRIMING", "STATE ACTIVE"),
        timeout=2.0, description="STATE PRIMING|ACTIVE",
    )

    s.bus.send("SET_CONFIG " + SMOKE_CONFIG)
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_STATE"),
        description="ERR BAD_STATE (SET_CONFIG during run)",
    )
    _abort_and_idle(s)


# --------------------------------------------------------------------------- #
# 5. Config-persistence across ABORT
# --------------------------------------------------------------------------- #

def t_config_persists_after_abort(s: Suite) -> None:
    """Config survives ABORT; START re-runs without re-uploading."""
    s.bus.send("SET_CONFIG " + FAST_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")
    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")
    _abort_and_idle(s)

    # Re-run without re-uploading config.
    s.bus.send("START")
    ack = s.bus.expect(
        lambda l: l in ("ACK START", "ERR NO_CONFIG"),
        description="ACK START (re-run, no SET_CONFIG)",
    )
    assert ack == "ACK START", f"config was not persisted after ABORT: {ack!r}"
    # Let the run finish cleanly.
    s.bus.expect(lambda l: l == "STATE IDLE", timeout=6.0, description="STATE IDLE")


# --------------------------------------------------------------------------- #
# 6. Edge-case config shapes
# --------------------------------------------------------------------------- #

def t_zero_active_duration(s: Suite) -> None:
    """duration_ms:0 → enterDone fires from enterActive; STATE ACTIVE never emitted."""
    s.bus.send("SET_CONFIG " + ZERO_ACTIVE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    # pump_ms=0 → STATE PRIMING is still announced, then immediately done.
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")

    # The next STATE-change must be DONE (not ACTIVE).
    first_state = s.bus.expect(
        lambda l: l in ("STATE DONE", "STATE ACTIVE"),
        timeout=3.0, description="STATE DONE (no ACTIVE expected)",
    )
    assert first_state == "STATE DONE", \
        f"expected skip-ACTIVE but saw: {first_state!r}"

    result = s.bus.expect(
        lambda l: l.startswith("RESULT "), timeout=2.0, description="RESULT",
    )
    assert '"run_id":"zero-active"' in result, f"wrong run_id: {result!r}"
    s.bus.expect(lambda l: l == "STATE IDLE", timeout=2.0, description="STATE IDLE")


def t_no_scheduled_actions(s: Suite) -> None:
    """Active phase with no scheduled actions completes on the duration timer alone."""
    s.bus.send("SET_CONFIG " + NO_SCHED_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE",
    )
    # No SCANNING should appear; just DONE after ~1.5 s.
    result_or_scan = s.bus.expect(
        lambda l: l.startswith("RESULT ") or l == "STATE SCANNING",
        timeout=5.0, description="RESULT (no scan expected)",
    )
    assert not result_or_scan.startswith("STATE SCANNING"), \
        "unexpected STATE SCANNING with no scheduled actions"
    # If we got RESULT we need to wait for STATE IDLE; DONE precedes RESULT on the wire.
    s.bus.expect(lambda l: l == "STATE IDLE", timeout=3.0, description="STATE IDLE")


def t_dispense_action(s: Suite) -> None:
    """DISPENSE scheduled action fires, pump runs, run reaches DONE."""
    s.bus.send("SET_CONFIG " + DISPENSE_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START", description="ACK START")
    s.bus.expect(
        lambda l: l in ("STATE PRIMING", "STATE ACTIVE"),
        timeout=2.0, description="STATE PRIMING|ACTIVE",
    )
    result = s.bus.expect(
        lambda l: l.startswith("RESULT "),
        timeout=12.0, description="RESULT (dispense run)",
    )
    assert '"run_id":"dispense-test"' in result, f"wrong run_id: {result!r}"
    s.bus.expect(lambda l: l == "STATE IDLE", timeout=2.0, description="STATE IDLE")


def t_hardware_homing_success(s: Suite) -> None:
    """Hardware-only homing success path.

    With the physical rig assembled, the switch may start OPEN; the motor
    should move until it closes, complete post-home travel, then continue the
    scan. If the switch never closes, this test fails.
    """
    s.bus.send("SET_CONFIG " + HOMING_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE",
    )
    s.bus.expect(
        lambda l: l == "STATE SCANNING",
        timeout=4.0, description="STATE SCANNING (homing path)",
    )
    telem = s.bus.expect(
        lambda l: l.startswith("TELEM ") and '"event":"well"' in l,
        timeout=25.0, description="TELEM well (after hardware homing)",
    )
    assert '"col":0' in telem, f"expected col 0, got: {telem!r}"
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=3.0, description="STATE ACTIVE (back from scan)",
    )
    _abort_and_idle(s)


# --------------------------------------------------------------------------- #
# 7. Sequential runs
# --------------------------------------------------------------------------- #

def t_multiple_sequential_runs(s: Suite) -> None:
    """Two back-to-back runs confirm timer/cursor reset between runs."""
    s.bus.send("SET_CONFIG " + FAST_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    for run_num in range(1, 3):
        s.bus.send("START")
        s.bus.expect(
            lambda l: l == "ACK START",
            description=f"ACK START (run {run_num})",
        )
        result = s.bus.expect(
            lambda l: l.startswith("RESULT "),
            timeout=6.0, description=f"RESULT (run {run_num})",
        )
        assert '"run_id":"fast"' in result, \
            f"wrong run_id on run {run_num}: {result!r}"
        assert '"status":"OK"' in result, \
            f"run {run_num} not OK: {result!r}"
        s.bus.expect(
            lambda l: l == "STATE IDLE",
            timeout=2.0, description=f"STATE IDLE (run {run_num})",
        )


# --------------------------------------------------------------------------- #
# 8. Hardware-only ERROR state (gate behind --hardware-home-timeout)
# --------------------------------------------------------------------------- #

def t_error_state_home_timeout(s: Suite) -> None:
    """HOME_TIMEOUT drives SM into ERROR; ABORT is the only escape.

    Requires: limit switch wired but held OPEN (or unwired with closedLevel=LOW)
    so that homing never completes. Times out after DEFAULT_HOME_TIMEOUT_MS (20 s).
    """
    s.bus.send("SET_CONFIG " + ERROR_TRIGGER_CONFIG)
    s.bus.expect(lambda l: l == "ACK SET_CONFIG", description="ACK SET_CONFIG")

    s.bus.send("START")
    s.bus.expect(lambda l: l == "ACK START",     description="ACK START")
    s.bus.expect(lambda l: l == "STATE PRIMING", description="STATE PRIMING")
    s.bus.expect(
        lambda l: l == "STATE ACTIVE",
        timeout=2.0, description="STATE ACTIVE",
    )
    s.bus.expect(
        lambda l: l == "STATE SCANNING",
        timeout=3.0, description="STATE SCANNING (homing starting)",
    )

    # Wait for HOME_TIMEOUT ERR and STATE ERROR. Allow 25 s.
    s.bus.expect(
        lambda l: l.startswith("ERR HOME_TIMEOUT") or l == "STATE ERROR",
        timeout=25.0, description="ERR HOME_TIMEOUT or STATE ERROR",
    )
    s.bus.expect(
        lambda l: l == "STATE ERROR",
        timeout=3.0, description="STATE ERROR",
    )

    # While in ERROR: START must be rejected; ABORT must recover.
    s.bus.send("START")
    s.bus.expect(
        lambda l: l.startswith("ERR BAD_STATE"),
        description="ERR BAD_STATE (START from ERROR)",
    )

    _abort_and_idle(s)
    _assert_hardware_idle(s, "after ERROR → ABORT")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3 runtime/state-machine regression tests")
    ap.add_argument("--port", default=None,
                    help="serial device (auto-detect if omitted)")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                    help=f"baud rate (default {DEFAULT_BAUD})")
    ap.add_argument("--boot-wait", type=float, default=2.5,
                    help="seconds to wait after opening port (default 2.5). "
                         "Set to 0 if the ESP32 is already running.")
    ap.add_argument("--hardware-homing-success", action="store_true",
                    help="Run the hardware homing success path. REQUIRES the limit switch "
                         "to close during homing, or to already read CLOSED.")
    ap.add_argument("--hardware-home-timeout", action="store_true",
                    help="Run the ERROR-state / HOME_TIMEOUT test. REQUIRES hardware "
                         "with the limit switch held OPEN so homing never completes. "
                         "Adds ~25 s to the run time.")
    args = ap.parse_args()

    port = args.port or auto_port()
    print(f"Opening {port} @ {args.baud}")
    bus = SerialBus(port, args.baud)
    try:
        if args.boot_wait > 0:
            time.sleep(args.boot_wait)
        for line in bus.read_lines(0.5):
            print(f"  [boot] {line}")

        suite = RuntimeSuite(bus)
        print("Running Phase 3 runtime/state-machine tests:\n")

        # ── 1. Config validation (before any valid SET_CONFIG) ────────────────
        print("[Config validation]")
        suite.run("SET_CONFIG bad JSON",           t_set_config_bad_json)
        suite.run("SET_CONFIG missing run_id",     t_set_config_missing_runid)
        suite.run("SET_CONFIG empty run_id",       t_set_config_empty_runid)
        suite.run("SET_CONFIG LED out of range",   t_set_config_bad_led)
        suite.run("SET_CONFIG too many wells",     t_set_config_too_many_wells)
        suite.run("SET_CONFIG missing active",     t_set_config_missing_active)
        suite.run("START with no config",          t_start_no_config)

        # ── 2. Full happy-path smoke run ──────────────────────────────────────
        print("\n[Happy path]")
        suite.run("Runtime smoke: scheduled scan", t_phase3_smoke)

        # ── 3. ABORT paths ────────────────────────────────────────────────────
        print("\n[ABORT paths]")
        suite.run("ABORT during PRIMING",          t_abort_during_priming)
        suite.run("ABORT during ACTIVE",           t_abort_during_active)
        suite.run("ABORT during SCANNING",         t_abort_during_scanning)

        # ── 4. State-guard enforcement ────────────────────────────────────────
        print("\n[State guards]")
        suite.run("START rejected during run",     t_start_rejected_during_run)
        suite.run("IDLE-only cmds rejected",       t_idle_cmds_rejected_during_run)
        suite.run("Read-only cmds work mid-run",   t_readonly_cmds_during_run)
        suite.run("SET_CONFIG rejected mid-run",   t_set_config_rejected_during_run)

        # ── 5. Config persistence ─────────────────────────────────────────────
        print("\n[Config persistence]")
        suite.run("Config persists after ABORT",   t_config_persists_after_abort)

        # ── 6. Edge-case configs ──────────────────────────────────────────────
        print("\n[Edge-case configs]")
        suite.run("Zero active duration",          t_zero_active_duration)
        suite.run("No scheduled actions",          t_no_scheduled_actions)
        suite.run("DISPENSE scheduled action",     t_dispense_action)

        # ── 7. Sequential runs ────────────────────────────────────────────────
        print("\n[Sequential runs]")
        suite.run("Two back-to-back runs",         t_multiple_sequential_runs)

        # ── 8. Hardware-only paths ───────────────────────────────────────────
        if args.hardware_homing_success:
            print("\n[Hardware homing success — physical rig required]")
            suite.run("Hardware homing success", t_hardware_homing_success)

        if args.hardware_home_timeout:
            print("\n[Hardware HOME_TIMEOUT — physical rig required]")
            suite.run("ERROR: HOME_TIMEOUT → ABORT", t_error_state_home_timeout)
        if not args.hardware_homing_success and not args.hardware_home_timeout:
            print("\n[Hardware-only paths skipped — pass --hardware-homing-success or --hardware-home-timeout]")

        return suite.summary()
    finally:
        # Safety stop: kill any running motor/pump/LED regardless of test outcome.
        try:
            bus.send("ABORT")
            time.sleep(0.3)
        except Exception:
            pass
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
