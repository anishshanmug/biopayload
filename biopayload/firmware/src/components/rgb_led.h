#ifndef BIOPAYLOAD_RGB_LED_H
#define BIOPAYLOAD_RGB_LED_H

// Common-cathode RGB LED driven by three PWM channels.
//
// Uses the ESP32 LEDC peripheral (Arduino-ESP32 2.x API) for smooth analog
// brightness control. Default channels are 0/1/2 at 5 kHz / 8-bit -- well
// outside any flicker-perception band and matched to the 0-255 LED_SET
// argument range.
//
// GPIO-only device: present() always returns true. The READY status from
// SYS_STATUS reflects "pin/channel setup did not fault", not "LED is wired".

#include <Arduino.h>

namespace components {

class RGBLed {
 public:
  // Default pins match the legacy demo: R on A1, G on A0, B on A2.
  static constexpr int DEFAULT_R = A1;
  static constexpr int DEFAULT_G = A0;
  static constexpr int DEFAULT_B = A2;

  // LEDC parameters chosen to match the LED_SET 0-255 contract directly.
  static constexpr uint32_t LEDC_FREQ_HZ      = 5000;
  static constexpr uint8_t  LEDC_RESOLUTION   = 8;     // 0..255 duty
  static constexpr uint8_t  LEDC_CHANNEL_R    = 0;
  static constexpr uint8_t  LEDC_CHANNEL_G    = 1;
  static constexpr uint8_t  LEDC_CHANNEL_B    = 2;

  RGBLed(int rPin = DEFAULT_R, int gPin = DEFAULT_G, int bPin = DEFAULT_B)
      : rPin_(rPin), gPin_(gPin), bPin_(bPin) {}

  bool begin() {
    ledcSetup(LEDC_CHANNEL_R, LEDC_FREQ_HZ, LEDC_RESOLUTION);
    ledcSetup(LEDC_CHANNEL_G, LEDC_FREQ_HZ, LEDC_RESOLUTION);
    ledcSetup(LEDC_CHANNEL_B, LEDC_FREQ_HZ, LEDC_RESOLUTION);
    ledcAttachPin(rPin_, LEDC_CHANNEL_R);
    ledcAttachPin(gPin_, LEDC_CHANNEL_G);
    ledcAttachPin(bPin_, LEDC_CHANNEL_B);
    off();
    return true;
  }

  bool present() const { return true; }

  // r/g/b in [0..255]. Caller is responsible for range-checking before this
  // is called (the LED_SET handler emits ERR BAD_ARG for out-of-range).
  void set(uint8_t r, uint8_t g, uint8_t b) {
    r_ = r; g_ = g; b_ = b;
    ledcWrite(LEDC_CHANNEL_R, r_);
    ledcWrite(LEDC_CHANNEL_G, g_);
    ledcWrite(LEDC_CHANNEL_B, b_);
  }

  void off() { set(0, 0, 0); }

  void abort() { off(); }

  uint8_t r() const { return r_; }
  uint8_t g() const { return g_; }
  uint8_t b() const { return b_; }

 private:
  int     rPin_, gPin_, bPin_;
  uint8_t r_ = 0, g_ = 0, b_ = 0;
};

}  // namespace components

#endif
