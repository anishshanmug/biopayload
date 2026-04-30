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
| `LINE_TOO_LONG` | Input line exceeded the 256-byte buffer |
| `PENDING_FULL` | Too many in-flight async DONEs (max 4) |
| `NO_SENSOR` | Spectral sensor not detected on I²C |
| `READ_FAIL` | Spectral read returned no data |
| `HOME_TIMEOUT` | `MOT_HOME` didn't see the limit switch close in time |

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

### System

| Command | Response | States | Description |
|---------|----------|--------|-------------|
| `PING` | `ACK PING` | any | Heartbeat |
| `HELLO` | `ACK HELLO <version>` | any | Handshake; firmware version |
| `STATE` | `STATE <name>` | any | Read current state-machine state |
| `SYS_STATUS` | `SYS_STATUS pump:… motor:… led:… limit:… spec:… state:…` | any | One-line snapshot of every component + state |
| `ABORT` | `ACK ABORT` | any | Emergency stop: clears pending DONEs, drives all components off, returns to IDLE |

---

## 2nd Order Commands — Orchestrator

These commands are **sequences of 1st order commands** that will be executed
by the firmware-side experiment runtime (Phase 3) given a JSON config.

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
