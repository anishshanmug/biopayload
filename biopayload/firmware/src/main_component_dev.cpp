/**
 * BioPayload firmware entry point (Arduino Nano ESP32).
 *
 * Phase 3 of the rework: state machine + dispatcher + 1st-order component
 * commands (PUMP_*, MOT_*, LED_*, LIM_*, SPEC_*) + cross-component
 * SYS_STATUS, plus the experiment runtime that walks PRIMING / ACTIVE /
 * SCANNING / DONE autonomously when given a JSON config via SET_CONFIG +
 * START.
 *
 * Wire protocol: see biopayload/firmware/COMMAND_REFERENCE.md.
 *   - 115200 8N1 over USB CDC
 *   - newline-delimited (\n) commands in, ACK / DONE / ERR / STATE / TELEM /
 *     RESULT / SYS_STATUS responses out
 *
 * The legacy single-character well-plate scan demo lives in
 * `main_demo_legacy.cpp`, excluded from build.
 *
 * Build & upload:  pio run -e component_dev -t upload
 * Monitor:         pio device monitor -e component_dev
 */

#include <Arduino.h>

#include "command/dispatcher.h"
#include "components/components.h"
#include "state/state_machine.h"

namespace {
constexpr uint32_t SERIAL_BAUD = 115200;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  // Brief wait so the host can attach the monitor in time to see the boot
  // banner; harmless on the ESP32 USB CDC.
  delay(500);

  Serial.println();
  Serial.println(F("BioPayload firmware booting (phase 3: experiment runtime online)"));

  // Per-component init. Prints `[boot] pump on pin 8 OK`, etc., so the
  // operator sees presence detection (real for I2C devices, "pin set up
  // cleanly" for GPIO devices) before any commands fly.
  biopayload::components::beginAll();

  biopayload::stateMachine.begin();

  Serial.println(F("Ready. Try: HELLO, SYS_STATUS, PUMP_RUN 250, LED_SET 64 0 0,"));
  Serial.println(F("            SET_CONFIG {\"run_id\":\"demo\",...}, START."));
}

void loop() {
  biopayload::dispatcher::poll();
  biopayload::components::tickAll();
  biopayload::stateMachine.tick(millis());
}
