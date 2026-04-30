// Phase 1 system commands: PING / HELLO / STATE / ABORT.
//
// These are the always-on handlers used to verify the dispatcher + state
// machine plumbing on a bare ESP32 before any peripherals are wired.

#include "command/dispatcher.h"
#include "command/parser.h"
#include "command/protocol.h"
#include "state/state_machine.h"

namespace biopayload {
namespace handlers {

constexpr const char* FIRMWARE_VERSION = "0.1.0";

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

}  // namespace handlers
}  // namespace biopayload
