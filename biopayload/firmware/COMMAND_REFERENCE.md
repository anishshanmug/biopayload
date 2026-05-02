# BioPayload Command Reference

Serial: **115200 8N1**, newline-delimited (`\n`).

## Response shapes

| Term | Meaning |
|------|---------|
| **ACK** | Immediate acknowledgement of receipt + arg validation |
| **DONE** | Asynchronous completion of a long-running operation |
| **ERR** | Failure (invalid args, bad state, hardware fault, …) |
| **STATE** | State-machine transition announcement (`STATE IDLE`, etc.) |
| **TELEM** | One-line JSON-ish payload (sensor data, etc.) |

Generic failure shape:

```text
ERR <code> [<message>]
```

Common error codes:

| Code | Cause |
|------|-------|
| `BAD_ARG` | Wrong arity or out-of-range argument |
| `BAD_STATE` | Command not allowed in the current state machine state |
| `UNKNOWN` | Command name not in the registry |
| `LINE_TOO_LONG` | Input line exceeded the 1 KB buffer |
| `PENDING_FULL` | Too many in-flight async DONEs (max 4) |
| `NO_SENSOR` | Spectral sensor not detected on I²C |
| `READ_FAIL` | Spectral read returned no data |
| `HOME_TIMEOUT` | `MOT_HOME` didn't see the limit switch close in time |
| `BAD_CONFIG` | `SET_CONFIG` JSON failed validation; the second word names the field |
| `NO_CONFIG` | `START` issued before any `SET_CONFIG` |

### Async DONE pattern

Long-running commands (`PUMP_RUN`, `MOT_MOVE`, `MOT_HOME`) follow:

```text
host  -> PUMP_RUN 250
fw    <- ACK PUMP_RUN          # immediately, after validation
fw    <- DONE PUMP_RUN         # ~250 ms later, after the op completes
```

If the op fails before completion, the failure is reported **before** DONE
and DONE is suppressed:

```text
host  -> MOT_HOME
fw    <- ACK MOT_HOME
fw    <- ERR HOME_TIMEOUT      # no DONE follows
```

### Component presence (READY vs NOT_FOUND)

Only the I²C-attached AS7341 spectral sensor has real presence detection:
`SPEC_STATUS` returns `NOT_FOUND` if the chip didn't ACK on the bus, and
the various `SPEC_*` commands fail with `ERR NO_SENSOR` until it's plugged
in (the firmware re-probes on each `SPEC_READ`).

GPIO-only components (pump, motor, RGB LED, limit switch) **cannot be
detected** from the MCU side -- there is no electrical way for the firmware
to tell whether anything is wired to a digital output, and a floating input
with a pull-up reads identically to an open switch. For those components,
`READY`/`OK` in the boot banner and `SYS_STATUS` mean "the firmware
configured the pin successfully", not "the device is physically present".

---

## 1st Order Commands — Component

Allowed states notation: most write/mutating commands are restricted to
`IDLE` so they can't race the experiment runtime; status reads are allowed
in any state.

### Peristaltic pump

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `PUMP_RUN <ms>` | `ACK PUMP_RUN` → `DONE PUMP_RUN` | IDLE | Run pump for N ms (0 = no-op + immediate DONE) |
| `PUMP_ON` | `ACK PUMP_ON` | IDLE | Latch pump on indefinitely |
| `PUMP_OFF` | `ACK PUMP_OFF` | IDLE | Turn pump off |
| `PUMP_STATUS` | `PUMP_STATUS RUNNING \| IDLE` | any | Query pump operational state |

### Spectral sensor (AS7341)

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `SPEC_READ` | `TELEM { f1, f2, …, f8, clear, nir }` | any | Read all 10 channels (synchronous, ~250 ms; `ERR NO_SENSOR` / `ERR READ_FAIL` on failure) |
| `SPEC_GAIN <0..10>` | `ACK SPEC_GAIN` | IDLE | 0=0.5×, 1=1×, 2=2×, … 10=512× |
| `SPEC_ATIME <0..255>` | `ACK SPEC_ATIME` | IDLE | Integration step count |
| `SPEC_ASTEP <0..65535>` | `ACK SPEC_ASTEP` | IDLE | Integration step time |
| `SPEC_STATUS` | `SPEC_STATUS READY \| NOT_FOUND` | any | I²C presence probe |

### Linear actuator

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `MOT_MOVE <steps>` | `ACK MOT_MOVE` → `DONE MOT_MOVE` | IDLE | Move N steps (+ forward, − reverse) |
| `MOT_RUN <FWD\|REV>` | `ACK MOT_RUN` | IDLE | Run continuously (no DONE) |
| `MOT_STOP` | `ACK MOT_STOP` | IDLE | Halt motion at next tick |
| `MOT_HOME` | `ACK MOT_HOME` → `DONE MOT_HOME` *or* `ERR HOME_TIMEOUT` | IDLE | Reverse until limit switch closes; zeros position. Times out at 5 s by default. |
| `MOT_POS` | `MOT_POS <signed_steps_from_home>` | any | Position counter (untrustworthy until at least one successful HOME) |
| `MOT_ENABLE` | `ACK MOT_ENABLE` | IDLE | Assert driver EN (hold torque) |
| `MOT_DISABLE` | `ACK MOT_DISABLE` | IDLE | Release driver EN |
| `MOT_STATUS` | `MOT_STATUS IDLE \| MOVING \| HOMING` | any | Query motor state |
| `MOT_INTERVAL <us>` | `ACK MOT_INTERVAL` | any | Set step pulse interval in µs (10–100000; default 120). Takes effect immediately, even mid-move. Lower = faster; TMC2208 stall risk below ~80 µs. |

### Limit switch

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `LIM_STATUS` | `LIM_STATUS OPEN \| CLOSED` | any | Read debounced switch level |

### RGB LED

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `LED_SET <r> <g> <b>` | `ACK LED_SET` | IDLE | Set color (0..255 per channel; LEDC PWM @ 5 kHz, 8-bit) |
| `LED_OFF` | `ACK LED_OFF` | IDLE | Turn off (R=G=B=0) |
| `LED_STATUS` | `LED_STATUS <r> <g> <b>` | any | Last commanded color |

### SD card

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `SD_STATUS` | `SD_STATUS READY total:<bytes> used:<bytes>` or `SD_STATUS NOT_FOUND` | any | Card presence + capacity (re-probes if absent) |
| `SD_LIST [path]` | `SD_FILE <name> DIR` or `SD_FILE <name> <bytes>` per entry, then `SD_LIST_END` | any | List entries in `path` (default `/`) |
| `SD_DELETE <path>` | `ACK SD_DELETE` or `ERR SD_FAIL <path>` | IDLE | Remove a single file |

**Implicit logging (no command needed):**
- `/events.log` is opened at boot and appended forever. Every state transition, `ABORT`, and experiment boundary is written automatically. Format: `T=<millis> <message>`.
- `/exp_NNN/scan.csv` is opened at experiment `START` and one row is appended immediately after each well reading during SCANNING. Header: `timestamp_ms,well_row,well_col,f1_415,f2_445,f3_480,f4_515,f5_555,f6_590,f7_630,f8_680,clear,nir`. The file is closed cleanly on DONE, ABORT, or ERROR.
- If the SD card is absent, all implicit logging is silently skipped and the experiment continues normally.

### System

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `PING` | `ACK PING` | any | Heartbeat |
| `HELLO` | `ACK HELLO <version>` | any | Handshake; firmware version |
| `STATE` | `STATE <name>` | any | Read current state-machine state |
| `SYS_STATUS` | `SYS_STATUS pump:… motor:… led:… limit:… spec:… sd:… state:…` | any | One-line snapshot of every component + state |
| `ABORT` | `ACK ABORT` | any | Emergency stop: clears pending DONEs, drives all components off, closes open SD files, returns to IDLE |

### Experiment control (Phase 3)

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `SET_CONFIG {json}` | `ACK SET_CONFIG` or `ERR BAD_CONFIG <field>` | IDLE | Upload an experiment description. The JSON payload follows the schema below; on parse / validation failure the second word of the ERR names the offending field. |
| `CLEAR_CONFIG` | `ACK CLEAR_CONFIG` | IDLE | Drop the stored experiment description. Useful for standalone runtime tests and for recovering to a known "no config loaded" state without rebooting the MCU. |
| `START` | `ACK START` then `STATE PRIMING` … `RESULT {…}` `STATE IDLE` | IDLE | Begin running the stored config. Errors with `ERR NO_CONFIG` if no config is loaded, or `ERR BAD_STATE START` if a run is already in progress. |

After `START`, the firmware drives the experiment autonomously and emits the
following over the wire:

```text
ACK START
STATE PRIMING                   # pump runs for priming.pump_ms
STATE ACTIVE                    # scheduled actions begin firing
STATE SCANNING                  # SCAN_ALL_WELLS triggered
TELEM {"event":"well","row":0,"col":0,"f1":...,"nir":...}
TELEM {"event":"well","row":0,"col":1,...}
STATE ACTIVE                    # back to ACTIVE between scans
... (more scheduled fires) ...
STATE DONE
RESULT {"run_id":"demo","status":"OK","scans":2,"wells":4,"duration_ms":8123}
STATE IDLE
```

`ABORT` at any point during a run is honored: the runtime closes the scan
CSV, drives all components off, and returns to IDLE without emitting RESULT.

#### `SET_CONFIG` JSON schema

```json
{
  "run_id": "demo-001",
  "priming": { "pump_ms": 1000 },
  "active": {
    "duration_ms": 8000,
    "scheduled": [
      { "cmd": "DISPENSE",       "every_ms": 4000, "pump_ms": 500 },
      { "cmd": "SCAN_ALL_WELLS", "every_ms": 3000 }
    ]
  },
  "scanning": {
    "homing": false,
    "settle_ms": 200,
    "led_off_after_read": true,
    "wells": [
      { "row": 0, "col": 0, "steps_from_home": 0,    "led": [255, 0, 0] },
      { "row": 0, "col": 1, "steps_from_home": 1200, "led": [255, 0, 0] }
    ]
  }
}
```

| Field | Type | Range | Notes |
|---|---|---|---|
| `run_id` | string | 1–31 chars | Required. Echoed back in `RESULT`. |
| `priming.pump_ms` | uint | 0–600 000 | Pump prime duration. `0` skips PRIMING. |
| `active.duration_ms` | uint | 0–86 400 000 | Total ACTIVE phase length. `0` skips straight to DONE. |
| `active.scheduled` | array | 0–4 entries | Periodic actions fired during ACTIVE. |
| `active.scheduled[].cmd` | string | `DISPENSE` \| `SCAN_ALL_WELLS` | |
| `active.scheduled[].every_ms` | uint | 1–86 400 000 | Period between fires; first fire is `every_ms` after ACTIVE entry. |
| `active.scheduled[].pump_ms` | uint | 1–600 000 | Required iff `cmd == DISPENSE`. |
| `scanning.homing` | bool | — | If `true`, SCANNING starts with a `MOT_HOME`. Set `false` for pre-wiring tests. Default `true`. |
| `scanning.settle_ms` | uint | 0–60 000 | Wait between LED-on and `SPEC_READ` per well. |
| `scanning.led_off_after_read` | bool | — | Default `true`. |
| `scanning.wells` | array | 0–12 entries | Empty array makes SCAN_ALL_WELLS a no-op (returns straight to ACTIVE). |
| `scanning.wells[].row` / `.col` | uint | row 0–7, col 0–11 | |
| `scanning.wells[].steps_from_home` | int | ±1 000 000 | Absolute target position; runtime computes `MOT_MOVE` delta from the current `motor.position()`. |
| `scanning.wells[].led` | `[r, g, b]` | each 0–255 | LED color for this well. |

The maximum line length the dispatcher will accept is 1 KB, which fits a
12-well config with comfortable margin.

If `SD_STATUS` is `READY`, every run also writes:
- one `--- exp NNN ---` separator line to `/events.log`
- one CSV row per well reading to `/exp_NNN/scan.csv`

---

## 2nd Order Commands — Orchestrator

These are the **sequences of 1st order commands** that the firmware-side
experiment runtime executes internally during `START` (Phase 3). They are not
directly callable over the wire — the runtime drives them based on the
`SET_CONFIG` payload — but they are documented here for reference because the
TELEM / RESULT trace they produce is the host's main view of a run.

### `PRIME_LINES`

1. `PUMP_RUN <prime_duration_ms>`
2. Wait for `DONE PUMP_RUN`

### `DISPENSE_MEDIA`

1. `PUMP_RUN <dispense_ms>`
2. Wait for `DONE PUMP_RUN`

### `SCAN_WELL (row, col)`

1. `MOT_MOVE <steps_to_well>`
2. Wait for `DONE MOT_MOVE`
3. `LED_SET <r> <g> <b>`
4. `SPEC_READ`
5. Log resulting `TELEM { … }`
6. `LED_OFF`

### `SCAN_ALL_WELLS`

1. `MOT_HOME`
2. Wait for `DONE MOT_HOME` (or fail on `ERR HOME_TIMEOUT`)
3. For `row` in `0..2`:
   - For `col` in `0..3`:
     - `SCAN_WELL(row, col)`

### `RUN_EXPERIMENT (config)`

1. Validate config (Phase 3: `SET_CONFIG` JSON)
2. `HELLO` → verify firmware connected
3. → State: **PRIMING**
4. `PRIME_LINES`
5. → State: **ACTIVE**
6. Loop:
   - **a.** Monitor temperature (TBD)
   - **b.** If dispense interval elapsed: `DISPENSE_MEDIA`
   - **c.** If scan interval elapsed:
     → State: **SCANNING** → `SCAN_ALL_WELLS` → State: **ACTIVE**
   - **d.** If experiment duration elapsed: break
7. → State: **DONE**
8. Log results, reset
9. → State: **IDLE**

### `ABORT_EXPERIMENT`

1. `ABORT`
2. → State: **IDLE**
