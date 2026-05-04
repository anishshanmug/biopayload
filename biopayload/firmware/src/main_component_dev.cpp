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
#include "esp_task_wdt.h"

#include "command/dispatcher.h"
#include "components/components.h"
#include "state/state_machine.h"

namespace {
constexpr uint32_t SERIAL_BAUD          = 115200;
constexpr uint32_t WATCHDOG_TIMEOUT_S   = 8;

// Decode esp_reset_reason() into a short tag printed at boot. Lets us
// distinguish a clean power-on from a watchdog or panic recovery in the trace.
const __FlashStringHelper* resetReasonTag(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return F("POWER_ON");
    case ESP_RST_EXT:       return F("EXT_PIN");
    case ESP_RST_SW:        return F("SW_REBOOT");
    case ESP_RST_PANIC:     return F("PANIC");
    case ESP_RST_INT_WDT:   return F("INT_WDT");
    case ESP_RST_TASK_WDT:  return F("TASK_WDT");
    case ESP_RST_WDT:       return F("OTHER_WDT");
    case ESP_RST_DEEPSLEEP: return F("DEEPSLEEP");
    case ESP_RST_BROWNOUT:  return F("BROWNOUT");
    case ESP_RST_SDIO:      return F("SDIO");
    default:                return F("UNKNOWN");
  }
}

void beginWatchdog() {
  // If a peripheral library blocks the main loop, reboot instead of leaving
  // the payload permanently unresponsive until a manual reset.
  //
  // TODO(Phase 4): on reboot, check esp_reset_reason() == ESP_RST_TASK_WDT
  // and call stateMachine.transitionTo(State::ERROR) with ERR WATCHDOG_RESET
  // before the boot banner. This ensures mid-experiment watchdog resets are
  // visible as experiment failures rather than silent restarts, and the SD
  // event log will capture the exact uptime when the hang occurred. Also mark
  // the most recent scan CSV as INTERRUPTED if RUN_DONE was not written.
  // Requires persistent RTC memory or a "run active" flag in NVS so the
  // reboot handler knows whether an experiment was in progress.
  esp_err_t initResult = esp_task_wdt_init(WATCHDOG_TIMEOUT_S, true);
  if (initResult != ESP_OK && initResult != ESP_ERR_INVALID_STATE) {
    Serial.print(F("[boot] watchdog init failed: "));
    Serial.println(static_cast<int>(initResult));
    return;
  }
  esp_err_t addResult = esp_task_wdt_add(nullptr);
  if (addResult != ESP_OK && addResult != ESP_ERR_INVALID_STATE) {
    Serial.print(F("[boot] watchdog add failed: "));
    Serial.println(static_cast<int>(addResult));
  } else {
    Serial.print(F("[boot] watchdog "));
    Serial.print(WATCHDOG_TIMEOUT_S);
    Serial.println(F("s OK"));
  }
}
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setTxTimeoutMs(50);
  // Brief wait so the host can attach the monitor in time to see the boot
  // banner; harmless on the ESP32 USB CDC.
  delay(500);

  Serial.println();
  Serial.println(F("BioPayload firmware booting (phase 3: experiment runtime online)"));
  esp_reset_reason_t reason = esp_reset_reason();
  Serial.print(F("[boot] reset "));
  Serial.print(resetReasonTag(reason));
  Serial.print(F(" ("));
  Serial.print(static_cast<int>(reason));
  Serial.println(F(")"));
  beginWatchdog();

  // Per-component init. Prints `[boot] pump on pin 8 OK`, etc., so the
  // operator sees presence detection (real for I2C devices, "pin set up
  // cleanly" for GPIO devices) before any commands fly.
  biopayload::components::beginAll();

  biopayload::stateMachine.begin();

  Serial.println(F("Ready. Try: HELLO, SYS_STATUS, PUMP_RUN 250, LED_SET 64 0 0,"));
  Serial.println(F("            SET_CONFIG {\"run_id\":\"demo\",...}, START."));
}

void loop() {
  esp_task_wdt_reset();
  biopayload::dispatcher::poll();
  biopayload::components::tickAll();
  biopayload::stateMachine.tick(millis());

  delay(1);
}
