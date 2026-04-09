#ifndef BIOPAYLOAD_SPECTRAL_SENSOR_H
#define BIOPAYLOAD_SPECTRAL_SENSOR_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AS7341.h>

namespace components {

struct SpectralReading {
  uint16_t f1_415nm;
  uint16_t f2_445nm;
  uint16_t f3_480nm;
  uint16_t f4_515nm;
  uint16_t f5_555nm;
  uint16_t f6_590nm;
  uint16_t f7_630nm;
  uint16_t f8_680nm;
  uint16_t clear;
  uint16_t nir;
};

class SpectralSensor {
 public:
  static const uint8_t DEFAULT_ADDR = 0x39;

  explicit SpectralSensor(uint8_t addr = DEFAULT_ADDR) : addr_(addr) {}

  bool begin() {
    Wire.begin();
    Wire.setClock(100000);
    delay(150);

    if (!as7341_.begin(addr_, &Wire)) {
      ready_ = false;
      return false;
    }
    as7341_.setATIME(100);
    as7341_.setASTEP(999);
    as7341_.setGain(AS7341_GAIN_256X);
    ready_ = true;
    return true;
  }

  bool isReady() const { return ready_; }

  bool read(SpectralReading &r) {
    if (!ready_) return false;
    if (!as7341_.readAllChannels()) return false;
    r.f1_415nm = as7341_.getChannel(AS7341_CHANNEL_415nm_F1);
    r.f2_445nm = as7341_.getChannel(AS7341_CHANNEL_445nm_F2);
    r.f3_480nm = as7341_.getChannel(AS7341_CHANNEL_480nm_F3);
    r.f4_515nm = as7341_.getChannel(AS7341_CHANNEL_515nm_F4);
    r.f5_555nm = as7341_.getChannel(AS7341_CHANNEL_555nm_F5);
    r.f6_590nm = as7341_.getChannel(AS7341_CHANNEL_590nm_F6);
    r.f7_630nm = as7341_.getChannel(AS7341_CHANNEL_630nm_F7);
    r.f8_680nm = as7341_.getChannel(AS7341_CHANNEL_680nm_F8);
    r.clear    = as7341_.getChannel(AS7341_CHANNEL_CLEAR);
    r.nir      = as7341_.getChannel(AS7341_CHANNEL_NIR);
    return true;
  }

  static void printReading(const SpectralReading &r) {
    Serial.print("415nm:"); Serial.print(r.f1_415nm);
    Serial.print(" 445nm:"); Serial.print(r.f2_445nm);
    Serial.print(" 480nm:"); Serial.print(r.f3_480nm);
    Serial.print(" 515nm:"); Serial.print(r.f4_515nm);
    Serial.print(" 555nm:"); Serial.print(r.f5_555nm);
    Serial.print(" 590nm:"); Serial.print(r.f6_590nm);
    Serial.print(" 630nm:"); Serial.print(r.f7_630nm);
    Serial.print(" 680nm:"); Serial.print(r.f8_680nm);
    Serial.print(" Clear:"); Serial.print(r.clear);
    Serial.print(" NIR:"); Serial.println(r.nir);
  }

  void setGain(as7341_gain_t gain) { as7341_.setGain(gain); }
  void setATIME(uint8_t atime) { as7341_.setATIME(atime); }
  void setASTEP(uint16_t astep) { as7341_.setASTEP(astep); }

  Adafruit_AS7341 &as7341() { return as7341_; }

 private:
  uint8_t addr_;
  Adafruit_AS7341 as7341_;
  bool ready_ = false;
};

}

#endif
