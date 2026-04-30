#ifndef BIOPAYLOAD_PERISTALTIC_PUMP_H
#define BIOPAYLOAD_PERISTALTIC_PUMP_H

// Single-channel peristaltic pump driven by a GPIO output.
//
// Three operating modes:
//   OFF        - pin LOW, idle
//   TIMED      - pin HIGH for a bounded duration, returns to OFF automatically
//                via update() when run_until_ deadline elapses (or sooner via
//                abort()). This is the mode used by `PUMP_RUN <ms>`.
//   INDEFINITE - pin HIGH until explicit off() / abort(). Used by `PUMP_ON`.
//
// GPIO-only device: no presence detection is possible from the MCU side.
// `begin()` always returns true; `present()` likewise. The READY status that
// `SYS_STATUS` reports for the pump means "firmware initialised the pin
// successfully", not "pump is physically connected".

#include <Arduino.h>

namespace components {

class PeristalticPump {
 public:
  enum class Mode : uint8_t { OFF = 0, TIMED = 1, INDEFINITE = 2 };

  static constexpr int DEFAULT_PIN = 6;

  explicit PeristalticPump(int pin = DEFAULT_PIN) : pin_(pin) {}

  // Configure the pin and drive it LOW. Returns true on success. GPIO-only,
  // so currently always true; signature mirrors the I2C components for
  // consistency.
  bool begin() {
    pinMode(pin_, OUTPUT);
    digitalWrite(pin_, LOW);
    mode_ = Mode::OFF;
    run_until_ = 0;
    return true;
  }

  bool present() const { return true; }

  // Latched on. Stays on until off() / abort() / startRunForMs() override.
  void on() {
    digitalWrite(pin_, HIGH);
    mode_ = Mode::INDEFINITE;
    run_until_ = 0;
  }

  void off() {
    digitalWrite(pin_, LOW);
    mode_ = Mode::OFF;
    run_until_ = 0;
  }

  // Blocking helper, kept for ad-hoc use; the firmware command path uses the
  // non-blocking startRunForMs + update pair instead.
  void runForMs(unsigned long duration_ms) {
    if (duration_ms == 0) return;
    on();
    delay(duration_ms);
    off();
  }

  // Non-blocking timed run. Pair with update() in the main loop.
  void startRunForMs(unsigned long duration_ms) {
    if (duration_ms == 0) {
      // Treat as a no-op rather than latching on; PUMP_RUN 0 should DONE
      // immediately without ever asserting the pin.
      off();
      return;
    }
    digitalWrite(pin_, HIGH);
    mode_ = Mode::TIMED;
    run_until_ = millis() + duration_ms;
  }

  // Drive any pending mode transitions. Safe to call every loop.
  void update() {
    if (mode_ != Mode::TIMED) return;
    if (static_cast<long>(millis() - run_until_) >= 0) {
      off();
    }
  }

  // Immediate stop: drive the pin LOW and clear mode. Required for ABORT to
  // work for PUMP_ON (INDEFINITE); `update()` only watches TIMED runs, so a
  // cooperative "set flag, wait for tick" path would never clear INDEFINITE.
  void abort() { off(); }

  bool running() const { return mode_ != Mode::OFF; }
  Mode mode() const     { return mode_; }
  int  pin() const      { return pin_; }

 private:
  int           pin_;
  Mode          mode_      = Mode::OFF;
  unsigned long run_until_ = 0;
};

}  // namespace components

#endif
