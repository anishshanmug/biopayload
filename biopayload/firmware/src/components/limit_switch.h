#ifndef BIOPAYLOAD_LIMIT_SWITCH_H
#define BIOPAYLOAD_LIMIT_SWITCH_H

// Mechanical limit switch on a single GPIO with internal pull-up.
//
// `closedLevel` selects the physical-switch convention:
//   - LOW (default):  switch shorts pin to GND when closed (pull-up reads
//                      HIGH when open, LOW when closed). This is the common
//                      micro-switch wiring.
//   - HIGH:           inverted -- closed = HIGH.
//
// Software debounce: an edge has to hold for `DEBOUNCE_MS` before closed()
// reports the new state. closed() only flips on the next read() call after
// the debounce interval, so call read() / closed() periodically (e.g. each
// loop) rather than once.
//
// Detection caveat: an unwired pin reads HIGH because of the pull-up, which
// is indistinguishable from a real switch sitting open. present() therefore
// always returns true; READY in SYS_STATUS means "pin set up", not "switch
// wired".

#include <Arduino.h>

namespace components {

class LimitSwitch {
 public:
  static constexpr int      DEFAULT_PIN     = D6;
  static constexpr uint16_t DEBOUNCE_MS     = 5;

  LimitSwitch(int pin = DEFAULT_PIN, uint8_t closedLevel = LOW)
      : pin_(pin), closedLevel_(closedLevel) {}

  bool begin() {
    pinMode(pin_, INPUT_PULLUP);
    raw_         = digitalRead(pin_);
    stable_      = raw_;
    lastChangeMs_ = millis();
    return true;
  }

  bool present() const { return true; }

  // Sample the pin and update the debounced state. Returns the current raw
  // (undebounced) level; most callers should use closed() instead.
  uint8_t read() {
    uint8_t level = digitalRead(pin_);
    if (level != raw_) {
      raw_ = level;
      lastChangeMs_ = millis();
    }
    if (level != stable_ && (millis() - lastChangeMs_) >= DEBOUNCE_MS) {
      stable_ = level;
    }
    return stable_;
  }

  bool closed() {
    return read() == closedLevel_;
  }

  // Cheap accessor for the last debounced state without another digitalRead.
  bool closedLatched() const { return stable_ == closedLevel_; }

  int pin() const { return pin_; }

 private:
  int           pin_;
  uint8_t       closedLevel_;
  uint8_t       raw_           = HIGH;
  uint8_t       stable_        = HIGH;
  unsigned long lastChangeMs_  = 0;
};

}  // namespace components

#endif
