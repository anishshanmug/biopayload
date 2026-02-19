/**
 * Peristaltic pump component
 *
 * Hardware: pump control pin wired to D6 (other side to GND).
 * Drive D6 HIGH to run the pump, LOW to stop.
 */

#ifndef BIOPAYLOAD_PERISTALTIC_PUMP_H
#define BIOPAYLOAD_PERISTALTIC_PUMP_H

#include <Arduino.h>

namespace components {

class PeristalticPump {
 public:
  static const int DEFAULT_PIN = 6;

  explicit PeristalticPump(int pin = DEFAULT_PIN) : pin_(pin) {}

  void begin() {
    pinMode(pin_, OUTPUT);
    off();
  }

  void on() { digitalWrite(pin_, HIGH); }

  void off() { digitalWrite(pin_, LOW); }

  // Blocking run (use only when you don't need serial/abort during run).
  void runForMs(unsigned long duration_ms) {
    if (duration_ms == 0) return;
    on();
    delay(duration_ms);
    off();
  }

  // Start a timed run; call update() every loop() for abort/timeout. 
  void startRunForMs(unsigned long duration_ms) {
    if (duration_ms == 0) return;
    abort_requested_ = false;
    run_until_ = millis() + duration_ms;
    on();
  }

  // Call every loop(); turns pump off when time expires or abort() was called. 
  void update() {
    if (!running()) return;
    if (abort_requested_ || (long)(millis() - run_until_) >= 0) {
      off();
      run_until_ = 0;
    }
  }

  void abort() { abort_requested_ = true; }

  bool running() const { return run_until_ != 0; }

  int pin() const { return pin_; }

 private:
  int pin_;
  unsigned long run_until_ = 0;   // 0 = idle
  bool abort_requested_ = false;
};

}  

#endif 
