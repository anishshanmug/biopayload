#ifndef BIOPAYLOAD_LINEAR_ACTUATOR_H
#define BIOPAYLOAD_LINEAR_ACTUATOR_H

#include <Arduino.h>

namespace components {

class LinearActuator {
 public:
  static const uint8_t STEP_BIT = 0;
  static const uint8_t DIR_BIT  = 7;
  static const uint8_t EN_BIT   = 1;
  bool enabled_ = false;

  static const unsigned long STEP_INTERVAL_US = 80;

  LinearActuator() {}

  void begin() {
    DDRB |= (1 << STEP_BIT) | (1 << EN_BIT);
    DDRD |= (1 << DIR_BIT);
    PORTB &= ~(1 << STEP_BIT);
    PORTD &= ~(1 << DIR_BIT);
    disable();
  }

  void enable()  { PORTB &= ~(1 << EN_BIT); }
  void disable() { PORTB |=  (1 << EN_BIT); }

  void setDirection(bool forward) {
    if (forward) PORTD &= ~(1 << DIR_BIT);
    else         PORTD |=  (1 << DIR_BIT);
  }

  void startContinuous(bool forward) {
    if(!enabled_) enable();
    setDirection(forward);
    continuous_ = true;
    remaining_steps_ = 0;
    abort_requested_ = false;
    last_step_us_ = micros();
  }

  void startMoveSteps(long steps) {
    if(!enabled_) enable();
    if (steps == 0) return;
    setDirection(steps > 0);
    remaining_steps_ = steps < 0 ? (unsigned long)(-steps) : (unsigned long)steps;
    continuous_ = false;
    abort_requested_ = false;
    last_step_us_ = micros();
  }

  void stop(bool disableOnStop = true) { abort_requested_ = true; continuous_ = false; if(disableOnStop) disable();}

  void abort() { abort_requested_ = true; continuous_ = false; }

  void update() {
    if (!continuous_ && remaining_steps_ == 0) return;
    if (abort_requested_) {
      remaining_steps_ = 0;
      return;
    }
    unsigned long now = micros();
    if ((unsigned long)(now - last_step_us_) >= STEP_INTERVAL_US) {
      PORTB |= (1 << STEP_BIT);
      __asm__ __volatile__("nop\nnop\nnop\n");
      PORTB &= ~(1 << STEP_BIT);
      if (!continuous_) remaining_steps_--;
      last_step_us_ = now;
    }
  }

  bool moving() const { return continuous_ || remaining_steps_ != 0; }
  unsigned long remainingSteps() const { return remaining_steps_; }

 private:
  unsigned long remaining_steps_ = 0;
  bool continuous_ = false;
  unsigned long last_step_us_ = 0;
  bool abort_requested_ = false;
};

}

#endif
