#ifndef BIOPAYLOAD_STATE_MACHINE_H
#define BIOPAYLOAD_STATE_MACHINE_H

// Top-level firmware state machine.
//
// Phase 1 of the build only exercises IDLE plus the universal ABORT path; the
// remaining states are wired in but their entry / tick / exit logic is filled
// in by the experiment runtime in a later phase.
//
// Every command in the dispatcher table carries an `allowedStates` bitmask
// built from stateMask(State::X). Use the MASK_* helpers below for the common
// combinations.

#include <stdint.h>

namespace biopayload {

enum class State : uint8_t {
  IDLE     = 0,
  PRIMING  = 1,
  ACTIVE   = 2,
  SCANNING = 3,
  DONE     = 4,
  ERROR    = 5,
};

constexpr uint8_t stateMask(State s) {
  return static_cast<uint8_t>(1u << static_cast<uint8_t>(s));
}

constexpr uint8_t MASK_ALL = stateMask(State::IDLE) | stateMask(State::PRIMING) |
                             stateMask(State::ACTIVE) | stateMask(State::SCANNING) |
                             stateMask(State::DONE) | stateMask(State::ERROR);
constexpr uint8_t MASK_IDLE_ONLY = stateMask(State::IDLE);
constexpr uint8_t MASK_RUNNING = stateMask(State::PRIMING) | stateMask(State::ACTIVE) |
                                 stateMask(State::SCANNING);

const char* stateName(State s);

class StateMachine {
 public:
  void begin();
  State current() const { return current_; }

  // Announce a transition over the wire and update `current_`. No-op if
  // `next == current_`. Phase 3 will hook entry / exit actions in here.
  void transitionTo(State next);

  // Drive the experiment runtime forward by one loop iteration. Phase 1 is a
  // no-op; the runtime hooks in here in phase 3.
  void tick(uint32_t now_ms);

  // Universal abort path: drop all hardware, clear pending DONEs, return to
  // IDLE. Returns true if the state actually moved.
  bool abort();

 private:
  State current_ = State::IDLE;
};

extern StateMachine stateMachine;

}  // namespace biopayload

#endif
