# Component dev – quick iteration

Minimal firmware for testing one component at a time. No SD card or full payload logic.

## Two boards, two firmwares

You have **two Arduinos** with different components. Each board gets its own firmware image and env:

| Board (example) | Components      | Environment            | Main file                  |
|------------------|-----------------|------------------------|----------------------------|
| **Nano**         | Pump only       | `nano_component_dev`   | `nano_component_dev.cpp`   |
| **Uno**          | Actuator only   | `uno_component_dev`   | `uno_component_dev.cpp`    |

**Workflow:**

1. **Upload to Nano (pump board):** Connect only the Nano, then:
   ```bash
   pio run -e nano_component_dev -t upload
   ```
2. **Upload to Uno (actuator board):** Connect only the Uno, then:
   ```bash
   pio run -e uno_component_dev -t upload
   ```
3. **Monitor:** Connect the board you want to talk to and run `pio device monitor`. If both are plugged in, use `pio device monitor --port /dev/cu.usbserial-XXXX` (or your port) to pick one.

**Optional:** If you ever put both components on a single board, use `component_dev` and `main_component_dev.cpp` (builds for Nano by default).

---

## Peristaltic pump (pump board)

- **Pins:** Edit `PIN_PUMP` in **`src/nano_component_dev.cpp`** (default 6). Other side of pump → GND.
- **API:** `components::PeristalticPump` in `include/components/peristaltic_pump.h`
  - `begin()`, `startRunForMs(ms)`, `update()`, `abort()`, `running()`, `on()`, `off()`

## Linear actuator (actuator board)

- **Hardware:** [Haydon Kerk Size 8 21mm](https://www.haydonkerkpittman.com/products/linear-actuators/hybrid-stepper/size-8), [TMC2208](https://www.analog.com/en/products/tmc2208.html) (Step/Dir/Enable).
- **Pins:** Edit `PIN_ACTUATOR_STEP`, `PIN_ACTUATOR_DIR`, `PIN_ACTUATOR_EN` in **`src/uno_component_dev.cpp`** (defaults 8, 7, 9). ENABLE is active-LOW; use `-1` if not connected.
- **API:** `components::LinearActuator` in `include/components/linear_actuator.h`
  - `begin()`, `startMoveSteps(steps)`, `update()`, `abort()`, `moving()`, `setStepIntervalUs(us)`, `moveSteps(steps)`, `enable()`, `disable()`

---

## Commands (Serial @ 115200)

**Pump board:** `PUMP <ms>` | `PING` | `ABORT`  

**Actuator board:** `ACTUATOR STEP <n> <0|1>` | `PING` | `ABORT`

---

## Build & upload summary

```bash
# Nano (pump board)
pio run -e nano_component_dev -t upload

# Uno (actuator board)
pio run -e uno_component_dev -t upload

# Monitor (after selecting port if needed)
pio device monitor
```

Use these envs to add and test more component modules; later you’ll orchestrate them in the main payload firmware (or from a host that talks to both boards).
