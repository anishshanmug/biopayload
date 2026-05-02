// System commands: PING / HELLO / STATE / ABORT / SYS_STATUS.
//
// These are the always-on handlers used to verify the dispatcher + state
// machine plumbing on a bare ESP32 before any peripherals are wired, plus
// the cross-component SYS_STATUS roll-up.

#include <Arduino.h>

#include "command/dispatcher.h"
#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"
#include "state/state_machine.h"

namespace biopayload {
namespace handlers {

constexpr const char* FIRMWARE_VERSION = "0.2.0";

void hPing(const ParsedCmd& /*cmd*/) {
  protocol::ack("PING");
}

void hHello(const ParsedCmd& /*cmd*/) {
  protocol::ackArg("HELLO", FIRMWARE_VERSION);
}

void hState(const ParsedCmd& /*cmd*/) {
  protocol::state(stateName(stateMachine.current()));
}

void hAbort(const ParsedCmd& /*cmd*/) {
  // ACK first, then drop any in-flight async work, then announce the IDLE
  // transition (transitionTo() is a no-op if we are already in IDLE, so the
  // wire trace stays clean).
  protocol::ack("ABORT");
  stateMachine.abort();
}

void hSysStatus(const ParsedCmd& /*cmd*/) {
  // Single-line cross-component snapshot. The pump/motor/led/limit fields
  // describe operational state (their begin() always succeeds on the MCU
  // side). Only `spec` does real I2C-based presence detection -- a
  // NOT_FOUND there means the AS7341 didn't ACK on the bus.
  Serial.print(F("SYS_STATUS"));

  Serial.print(F(" pump:"));
  Serial.print(components::pump.running() ? F("RUNNING") : F("IDLE"));

  Serial.print(F(" motor:"));
  switch (components::motor.status()) {
    case ::components::LinearActuator::Status::IDLE:   Serial.print(F("IDLE")); break;
    case ::components::LinearActuator::Status::MOVING: Serial.print(F("MOVING")); break;
    case ::components::LinearActuator::Status::HOMING: Serial.print(F("HOMING")); break;
  }

  Serial.print(F(" led:"));
  if (components::led.r() == 0 && components::led.g() == 0 && components::led.b() == 0) {
    Serial.print(F("OFF"));
  } else {
    Serial.print(F("ON"));
  }

  Serial.print(F(" limit:"));
  Serial.print(components::limit.closed() ? F("CLOSED") : F("OPEN"));

  Serial.print(F(" spec:"));
  Serial.print(components::spec.isReady() ? F("READY") : F("NOT_FOUND"));

  Serial.print(F(" sd:"));
  Serial.print(components::sd.present() ? F("READY") : F("NOT_FOUND"));

  Serial.print(F(" state:"));
  Serial.println(stateName(stateMachine.current()));
}

}  // namespace handlers
}  // namespace biopayload
