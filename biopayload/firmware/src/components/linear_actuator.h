#ifndef BIOPAYLOAD_LINEAR_ACTUATOR_H
#define BIOPAYLOAD_LINEAR_ACTUATOR_H

// ESP32-friendly stepper-motor driver for the TMC2208 + Haydon Kerk Size 8
// linear actuator. Replaces the AVR-only register-poking version of this
// header that lived here previously.
//
// Non-blocking: callers issue startMoveSteps() / startContinuous() / startHome()
// and then call update() every loop iteration. update() generates STEP pulses
// at the configured interval, tracks signed position (steps from home), and
// self-completes when the operation's exit condition is met (step counter hits
// zero, limit switch closes, homing deadline elapses).
//
// Modes (visible via status()):
//   IDLE     - no motion in progress
//   MOVING   - executing startMoveSteps() / startContinuous()
//   HOMING   - executing startHome(); two-phase sequence:
//                Phase 1: reverse continuously until limit switch closes.
//                Phase 2: if postHomeSteps_ > 0, continue reverse for that
//                         many more steps (post-home travel to the true zero
//                         reference, e.g. flush with back wall). Status stays
//                         HOMING throughout so the dispatcher sees one async op.
//              On completion pos_ = 0. On timeout (phase 1 only), homeFailed()
//              goes true and the caller emits `ERR HOME_TIMEOUT`.
//
// Position semantics: pos_ is a signed step counter relative to the most
// recent successful home. Forward steps increment it, reverse steps
// decrement. During HOMING the counter is NOT updated (zeroed on success);
// homed() returns false until at least one home has succeeded.
//
// Driver enable convention: TMC2208's EN pin is active-LOW. Constructor
// accepts -1 for `enPin` if EN is hard-tied to GND on the board.

#include <Arduino.h>

#include "components/limit_switch.h"

namespace components {

class LinearActuator {
 public:
  enum class Status : uint8_t { IDLE = 0, MOVING = 1, HOMING = 2 };

  static constexpr int           DEFAULT_PIN_STEP        = 4;
  static constexpr int           DEFAULT_PIN_DIR         = 2;
  static constexpr int           DEFAULT_PIN_EN          = 3;
  static constexpr unsigned long DEFAULT_STEP_INTERVAL_US = 120;
  static constexpr unsigned long DEFAULT_HOME_TIMEOUT_MS  = 20000;

  LinearActuator(int stepPin = DEFAULT_PIN_STEP,
                 int dirPin  = DEFAULT_PIN_DIR,
                 int enPin   = DEFAULT_PIN_EN)
      : pinStep_(stepPin), pinDir_(dirPin), pinEn_(enPin) {}

  bool begin() {
    pinMode(pinStep_, OUTPUT);
    pinMode(pinDir_, OUTPUT);
    if (pinEn_ >= 0) pinMode(pinEn_, OUTPUT);
    digitalWrite(pinStep_, LOW);
    digitalWrite(pinDir_, HIGH);
    setEnabled_(false);
    forward_ = true;
    return true;
  }

  bool present() const { return true; }

  void enable()   { setEnabled_(true); }
  void disable()  { setEnabled_(false); }
  bool enabled() const { return enabled_; }

  void setDirection(bool forward) {
    forward_ = forward;
    digitalWrite(pinDir_, forward ? HIGH : LOW);
  }

  // Bounded N-step motion. Positive = forward, negative = reverse.
  void startMoveSteps(long steps) {
    if (steps == 0) {
      stopMotion_();
      status_ = Status::IDLE;
      return;
    }
    if (!enabled_) enable();
    setDirection(steps > 0);
    remainingSteps_ = (steps > 0) ? static_cast<unsigned long>(steps)
                                  : static_cast<unsigned long>(-steps);
    continuous_      = false;
    abort_requested_ = false;
    lastStepUs_      = micros();
    status_          = Status::MOVING;
  }

  void startContinuous(bool forward) {
    if (!enabled_) enable();
    setDirection(forward);
    continuous_      = true;
    remainingSteps_  = 0;
    abort_requested_ = false;
    lastStepUs_      = micros();
    status_          = Status::MOVING;
  }

  // Reverse continuously until limit switch closes; zero position on success.
  // On timeout, sets homeFailed_ true and stops -- caller emits the ERR.
  void startHome(LimitSwitch& sw, unsigned long timeoutMs = DEFAULT_HOME_TIMEOUT_MS) {
    if (!enabled_) enable();
    setDirection(false);
    continuous_       = true;
    remainingSteps_   = 0;
    abort_requested_  = false;
    lastStepUs_       = micros();
    homingSwitch_      = &sw;
    homingDeadlineMs_  = millis() + timeoutMs;
    homeFailed_        = false;
    postHomeTraveling_ = false;
    status_            = Status::HOMING;
  }

  // Cooperative stop. Halts at next update(). Does NOT toggle enable.
  void stop()  { abort_requested_ = true; }
  void abort() { abort_requested_ = true; }

  void update() {
    if (status_ == Status::IDLE) return;

    if (abort_requested_) {
      stopMotion_();
      status_ = Status::IDLE;
      return;
    }

    if (status_ == Status::HOMING) {
      if (!postHomeTraveling_) {
        // Phase 1: seek the switch.
        if (homingSwitch_ && homingSwitch_->closed()) {
          homingSwitch_ = nullptr;  // stop polling switch
          if (postHomeSteps_ > 0) {
            // Transition to phase 2: pos_ starts at the offset and counts
            // down to 0 as the stage travels the remaining distance.
            pos_               = static_cast<long>(postHomeSteps_);
            continuous_        = false;
            remainingSteps_    = postHomeSteps_;
            postHomeTraveling_ = true;
          } else {
            stopMotion_();
            pos_    = 0;
            homed_  = true;
            status_ = Status::IDLE;
            return;
          }
        } else if (static_cast<long>(millis() - homingDeadlineMs_) >= 0) {
          stopMotion_();
          homeFailed_ = true;
          status_     = Status::IDLE;
          return;
        }
      }
      // Phase 2 completion is handled below in the !continuous_ block.
    }

    unsigned long now = micros();
    if ((now - lastStepUs_) < stepIntervalUs_) return;
    lastStepUs_ = now;

    pulseStep_();

    // Position counter ticks for MOVING and during post-home travel (phase 2),
    // but stays put during the switch-seek phase (phase 1 of HOMING).
    if (status_ != Status::HOMING || postHomeTraveling_) {
      pos_ += forward_ ? 1 : -1;
    }

    if (!continuous_) {
      if (--remainingSteps_ == 0) {
        if (postHomeTraveling_) {
          // Phase 2 complete: we are now at the true zero reference.
          postHomeTraveling_ = false;
          pos_   = 0;
          homed_ = true;
        }
        stopMotion_();
        status_ = Status::IDLE;
      }
    }
  }

  Status        status() const         { return status_; }
  bool          moving() const         { return status_ != Status::IDLE; }
  long          position() const       { return pos_; }
  bool          homed() const          { return homed_; }
  bool          homeFailed() const     { return homeFailed_; }
  void          clearHomeFailed()      { homeFailed_ = false; }
  void          setStepIntervalUs(unsigned long us) { stepIntervalUs_ = us; }
  unsigned long stepIntervalUs() const { return stepIntervalUs_; }

  // Extra reverse steps to travel after the switch closes before zeroing pos_.
  // Set to 9333 to make the back wall (9333 steps past the switch) position 0.
  // Default 0 means switch position = zero (no post-home travel).
  void          setPostHomeSteps(unsigned long steps) { postHomeSteps_ = steps; }
  unsigned long postHomeSteps() const                 { return postHomeSteps_; }

 private:
  void pulseStep_() {
    digitalWrite(pinStep_, HIGH);
    delayMicroseconds(1);
    digitalWrite(pinStep_, LOW);
  }
  void setEnabled_(bool en) {
    if (pinEn_ >= 0) digitalWrite(pinEn_, en ? LOW : HIGH);  // active-LOW
    enabled_ = en;
  }
  void stopMotion_() {
    continuous_        = false;
    remainingSteps_    = 0;
    homingSwitch_      = nullptr;
    postHomeTraveling_ = false;
    abort_requested_   = false;
  }

  int           pinStep_;
  int           pinDir_;
  int           pinEn_;
  unsigned long stepIntervalUs_  = DEFAULT_STEP_INTERVAL_US;
  unsigned long lastStepUs_      = 0;

  Status        status_           = Status::IDLE;
  bool          enabled_          = false;
  bool          forward_          = true;
  bool          homed_            = false;
  bool          homeFailed_       = false;
  bool          continuous_       = false;
  bool          abort_requested_  = false;

  long          pos_               = 0;
  unsigned long remainingSteps_    = 0;
  unsigned long postHomeSteps_     = 0;
  bool          postHomeTraveling_ = false;

  LimitSwitch*  homingSwitch_     = nullptr;
  unsigned long homingDeadlineMs_ = 0;
};

}  // namespace components

#endif
