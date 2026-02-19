/**
 * Linear actuator component (stepper + TMC2208 or similar Step/Dir driver)
 *
 * Hardware: Haydon Kerk 21F4U-2.5-B27 Size 8 21mm (1.8° bipolar, non-captive)
 * Driver:   TMC2208 in STEP/DIR mode
 * Wiring:   STEP=D8 (PORTB0), DIR=D7 (PORTD7), EN=D9 (PORTB1)
 *           Enable is active-LOW on TMC2208.
 *
 * Uses direct port manipulation for reliable high-speed stepping.
 * Pin assignments are fixed to D8/D7/D9 (ATmega328P PORTB/PORTD).
 *
 * Motor specs:
 *   Rated voltage:    2.5 VDC
 *   Current/phase:    0.49 A
 *   Resistance/phase: 5.1 ohm
 *   Step angle:       1.8 deg (200 steps/rev)
 */

#ifndef BIOPAYLOAD_LINEAR_ACTUATOR_H
#define BIOPAYLOAD_LINEAR_ACTUATOR_H

#include <Arduino.h>

namespace components {

class LinearActuator {
 public:
  // Fixed pin→port mapping for ATmega328P (Uno/Nano).
  // Pin 8  = PORTB bit 0 (STEP)
  // Pin 7  = PORTD bit 7 (DIR)
  // Pin 9  = PORTB bit 1 (EN)
  static const uint8_t STEP_BIT = 0;  // PORTB
  static const uint8_t DIR_BIT  = 7;  // PORTD
  static const uint8_t EN_BIT   = 1;  // PORTB
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

}  // namespace components

#endif  // BIOPAYLOAD_LINEAR_ACTUATOR_H
