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

  void runForMs(unsigned long duration_ms) {
    if (duration_ms == 0) return;
    on();
    delay(duration_ms);
    off();
  }

  void startRunForMs(unsigned long duration_ms) {
    if (duration_ms == 0) return;
    abort_requested_ = false;
    run_until_ = millis() + duration_ms;
    on();
  }

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
  unsigned long run_until_ = 0;
  bool abort_requested_ = false;
};

}

#endif
