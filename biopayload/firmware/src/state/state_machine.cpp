#include "state/state_machine.h"

#include "command/dispatcher.h"
#include "command/protocol.h"
#include "components/components.h"
#include "state/experiment.h"
#include "state/sd_logger.h"

namespace biopayload {

StateMachine stateMachine;

const char* stateName(State s) {
  switch (s) {
    case State::IDLE:     return "IDLE";
    case State::PRIMING:  return "PRIMING";
    case State::ACTIVE:   return "ACTIVE";
    case State::SCANNING: return "SCANNING";
    case State::DONE:     return "DONE";
    case State::ERROR:    return "ERROR";
  }
  return "UNKNOWN";
}

void StateMachine::begin() {
  current_ = State::IDLE;
  protocol::state(stateName(current_));
}

void StateMachine::transitionTo(State next) {
  if (next == current_) return;
  current_ = next;
  protocol::state(stateName(current_));
  // Mirror every state transition to the SD event log (no-op if card absent).
  sdLogger::logEvent(stateName(current_));
}

void StateMachine::tick(uint32_t now_ms) {
  // Drive the Phase 3 experiment runtime. It walks PRIMING / ACTIVE /
  // SCANNING / DONE / ERROR by calling back into transitionTo(); IDLE / DONE
  // / ERROR are no-ops on its side so the state machine is also safe to tick
  // when no experiment is running.
  experiment::tick(now_ms);
}

bool StateMachine::abort() {
  // Cooperative all-stop: cancel pending DONEs (no failure messages emitted)
  // and tell every component to drop to a safe state. This runs every time
  // ABORT is received, including in IDLE -- if a manual PUMP_ON is latched on
  // and the operator hits ABORT, we still need the pump to drop.
  dispatcher::clearPending();
  components::abortAll();
  // Reset the experiment runtime's cursors / sub-state. We deliberately keep
  // the stored config so the operator can re-issue START without re-uploading.
  experiment::onAbort();
  sdLogger::logEvent("ABORT");
  // Close any open scan file so data is flushed cleanly.
  sdLogger::endScan();
  if (current_ == State::IDLE) return false;
  transitionTo(State::IDLE);
  return true;
}

}  // namespace biopayload
