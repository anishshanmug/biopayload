/**
 * BioPayload firmware entry point (Arduino Nano ESP32).
 *
 * Phase 1 of the rework: thin shell that delegates everything to the command
 * dispatcher and the state machine. Component setup, the experiment runtime,
 * and the 1st-order command handlers are filled in by later phases.
 *
 * Wire protocol: see biopayload/firmware/COMMAND_REFERENCE.md.
 *   - 115200 8N1 over USB CDC
 *   - newline-delimited (\n) commands in, ACK / DONE / ERR / STATE / TELEM
 *     responses out
 *
 * The legacy single-character well-plate scan demo lives in
 * `main_demo_legacy.cpp`, excluded from build.
 *
 * Build & upload:  pio run -e component_dev -t upload
 * Monitor:         pio device monitor -e component_dev
 */

#include <Arduino.h>

#include "command/dispatcher.h"
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
  Serial.println(F("BioPayload firmware booting (phase 1: protocol skeleton)"));
  Serial.println(F("Send 'PING' or 'HELLO' to verify the wire."));

  biopayload::stateMachine.begin();
}

void loop() {
  biopayload::dispatcher::poll();
  biopayload::stateMachine.tick(millis());
}
