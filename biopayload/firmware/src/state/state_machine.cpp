#include "state/state_machine.h"

#include "command/dispatcher.h"
#include "command/protocol.h"

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
}

void StateMachine::tick(uint32_t /*now_ms*/) {
  // Phase 3: experiment runtime steps here. Intentionally empty for now so
  // that phase 1 builds and exercises only the dispatcher + ABORT path.
}

bool StateMachine::abort() {
  // Phase 2 will plug in components::abortAll() here. For phase 1 we just
  // tear down any pending async DONEs and snap back to IDLE.
  dispatcher::clearPending();
  if (current_ == State::IDLE) return false;
  transitionTo(State::IDLE);
  return true;
}

}  // namespace biopayload
