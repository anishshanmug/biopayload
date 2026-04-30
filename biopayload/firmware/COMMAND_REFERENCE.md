# BioPayload Command Reference

Serial: **115200 8N1**, newline-delimited (`\n`).

| Term | Meaning |
|------|---------|
| **ACK** | Immediate acknowledgement |
| **DONE** | Asynchronous completion (after the operation finishes) |

Any command may return:

```text
ERR <code> <message>
```

on failure.

---

## 1st Order Commands — Component

### Peristaltic pump

| Command | Response | Description |
|---------|----------|-------------|
| `PUMP_RUN <ms>` | `ACK` → `DONE PUMP_RUN` | Run pump for N milliseconds |
| `PUMP_ON` | `ACK PUMP_ON` | Turn pump on indefinitely |
| `PUMP_OFF` | `ACK PUMP_OFF` | Turn pump off |
| `PUMP_STATUS` | `PUMP_STATUS RUNNING \| IDLE` | Query pump state |

### Spectral sensor (AS7341)

| Command | Response | Description |
|---------|----------|-------------|
| `SPEC_READ` | `SPEC_DATA <f1> <f2> ... <f8> <clear> <nir>` | Read all 10 channels |
| `SPEC_GAIN <0-10>` | `ACK SPEC_GAIN` | Set gain (0 = 1× … 10 = 256×) |
| `SPEC_ATIME <0-255>` | `ACK SPEC_ATIME` | Amount of steps |
| `SPEC_ASTEP <0-65534>` | `ACK SPEC_ASTEP` | Time of step |
| `SPEC_STATUS` | `SPEC_STATUS READY \| NOT_FOUND` | Query sensor presence |

### Linear actuator

| Command | Response | Description |
|---------|----------|-------------|
| `MOT_MOVE <steps>` | `ACK` → `DONE MOT_MOVE` | Move N steps (+ forward, − reverse) |
| `MOT_RUN <FWD\|REV>` | `ACK MOT_RUN` | Run continuously |
| `MOT_STOP` | `ACK MOT_STOP` | Stop and disable driver |
| `MOT_HOME` | `ACK` → `DONE MOT_HOME` | Reverse until limit switch, set zero |
| `MOT_POS` | `MOT_POS <steps>` | Query position from home |
| `MOT_ENABLE` | `ACK MOT_ENABLE` | Enable driver (hold torque) |
| `MOT_DISABLE` | `ACK MOT_DISABLE` | Disable driver (release) |
| `MOT_STATUS` | `MOT_STATUS IDLE \| MOVING \| HOMING` | Query motor state |

### Limit switch

| Command | Response | Description |
|---------|----------|-------------|
| `LIM_STATUS` | `LIM_STATUS OPEN \| CLOSED` | Query limit switch |

### RGB LED

| Command | Response | Description |
|---------|----------|-------------|
| `LED_SET <r> <g> <b>` | `ACK LED_SET` | Set color (0–255 per channel) |
| `LED_OFF` | `ACK LED_OFF` | Turn off |
| `LED_STATUS` | `LED_STATUS <r> <g> <b>` | Query current color |

### System

| Command | Response | Description |
|---------|----------|-------------|
| `PING` | `ACK PING` | Heartbeat |
| `HELLO` | `ACK HELLO <version>` | Handshake |
| `ABORT` | `ACK ABORT` | Emergency stop all components |

---

## 2nd Order Commands — Orchestrator

These commands are **sequences of 1st order commands** executed by the Python state machine (ground station), not necessarily single messages on the wire.

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
5. Receive `SPEC_DATA` → log result
6. `LED_OFF`

### `SCAN_ALL_WELLS`

1. `MOT_HOME`
2. Wait for `DONE MOT_HOME`
3. For `row` in `0..2`:
   - For `col` in `0..3`:
     - `SCAN_WELL(row, col)`

### `RUN_EXPERIMENT (config)`

1. Validate config
2. `HELLO` → verify both boards connected
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

1. `ABORT` (both boards)
2. → State: **IDLE**
