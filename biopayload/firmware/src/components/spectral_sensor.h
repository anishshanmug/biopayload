#ifndef BIOPAYLOAD_SPECTRAL_SENSOR_H
#define BIOPAYLOAD_SPECTRAL_SENSOR_H

// Spectral sensor (Adafruit AS7341) with three layers of hang protection:
//
//  Layer 1 — Circuit breaker
//    After FAIL_THRESHOLD consecutive read failures, ready_ is cleared and
//    further reads return false immediately until tryReconnect() succeeds.
//    Prevents repeated blocking attempts on a degraded sensor.
//
//  Layer 2 — I2C bus recovery
//    After any read failure, recoverI2C_() bit-bangs 9 SCL pulses to unstick
//    a held-low SDA line, then calls Wire.end()/Wire.begin() to flush the
//    Arduino I2C state machine. This is the standard I2C recovery procedure.
//
//  Layer 3 — FreeRTOS task timeout
//    readAllChannels() is launched in a short-lived FreeRTOS task. loop()
//    waits on a binary semaphore with READ_TIMEOUT_MS deadline. If the task
//    does not complete in time the semaphore is not given, loop() returns
//    immediately, and the next call to read() runs I2C recovery. The firmware
//    main loop is never blocked longer than READ_TIMEOUT_MS.
//
// Wire.setTimeOut(50) (set in begin()) covers individual I2C byte-level
// transactions; the FreeRTOS wrapper covers the full multi-byte polling loop
// inside readAllChannels() which Wire's timeout does not bound end-to-end.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AS7341.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

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
  static const uint8_t  DEFAULT_ADDR      = 0x39;
  static const uint32_t READ_TIMEOUT_MS   = 1000;  // max time for a full read
  static const uint8_t  FAIL_THRESHOLD    = 3;     // circuit-breaker trip count

  explicit SpectralSensor(uint8_t addr = DEFAULT_ADDR) : addr_(addr) {
    sem_ = xSemaphoreCreateBinary();
  }

  bool begin() {
    Wire.begin();
    Wire.setClock(100000);
    Wire.setTimeOut(50);
    delay(150);

    if (!as7341_.begin(addr_, &Wire)) {
      ready_ = false;
      return false;
    }
    as7341_.setATIME(100);
    as7341_.setASTEP(999);
    as7341_.setGain(AS7341_GAIN_256X);
    ready_    = true;
    failCount_ = 0;
    return true;
  }

  // Result type for the async pollRead() API.
  enum class ReadResult : uint8_t { PENDING, DONE, FAILED };

  bool isReady() const { return ready_; }
  bool present() const { return ready_; }
  uint8_t address() const { return addr_; }

  bool tryReconnect() {
    if (ready_) return true;
    failCount_ = 0;
    return begin();
  }

  // -------------------------------------------------------------------------
  // Async API — used by hSpecRead via the dispatcher's pending-DONE tracker.
  //
  // Usage:
  //   if (!spec.startRead(&r)) { emit ERR; return; }
  //   emit ACK;
  //   register pending DoneCheck that calls spec.pollRead()
  //
  // pollRead() is non-blocking. It checks the semaphore, handles the timeout,
  // and runs I2C recovery on failure — all without blocking loop().
  // -------------------------------------------------------------------------

  // Launch the background read task. r must stay valid until pollRead()
  // returns DONE or FAILED. Returns false if the sensor is not ready or
  // a read is already in flight.
  bool startRead(SpectralReading* r) {
    if (!ready_ || readInProgress_) return false;
    readCtx_.sensor  = this;
    readCtx_.result  = r;
    readCtx_.success = false;
    readDeadlineMs_  = millis() + READ_TIMEOUT_MS;
    xSemaphoreTake(sem_, 0);  // drain any leftover from a previous read
    readInProgress_  = true;
    taskHandle_      = nullptr;
    BaseType_t ok = xTaskCreate(
        readTask_, "spec_read", 4096, &readCtx_,
        configMAX_PRIORITIES - 1, &taskHandle_);
    if (ok != pdPASS) {
      readInProgress_ = false;
      onFailure_();
      return false;
    }
    return true;
  }

  // Poll for completion. Call every loop() iteration after startRead().
  // DONE   → reading is in *r; TELEM should be emitted by the caller.
  // FAILED → ERR should be emitted; I2C recovery already ran.
  // PENDING → not finished yet; call again next loop().
  ReadResult pollRead() {
    if (!readInProgress_) return ReadResult::FAILED;

    if (xSemaphoreTake(sem_, 0) == pdTRUE) {
      // Task finished and gave the semaphore.
      readInProgress_ = false;
      taskHandle_     = nullptr;
      if (!readCtx_.success) {
        onFailure_();
        return ReadResult::FAILED;
      }
      failCount_ = 0;
      return ReadResult::DONE;
    }

    // Check wall-clock timeout.
    if (static_cast<long>(millis() - readDeadlineMs_) >= 0) {
      if (taskHandle_) {
        vTaskDelete(taskHandle_);
        taskHandle_ = nullptr;
      }
      readInProgress_ = false;
      onFailure_();
      return ReadResult::FAILED;
    }

    return ReadResult::PENDING;
  }

  // -------------------------------------------------------------------------
  // Blocking read — used by experiment.cpp during SCANNING where the
  // experiment sub-state machine can tolerate up to READ_TIMEOUT_MS of
  // latency in the loop. Internally reuses the same task+semaphore so all
  // three protection layers still apply.
  // -------------------------------------------------------------------------
  bool read(SpectralReading &r) {
    if (!startRead(&r)) return false;
    ReadResult res;
    do {
      vTaskDelay(pdMS_TO_TICKS(1));
      res = pollRead();
    } while (res == ReadResult::PENDING);
    return res == ReadResult::DONE;
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
    Serial.print(" NIR:");   Serial.println(r.nir);
  }

  void setGain(as7341_gain_t gain) { as7341_.setGain(gain); }
  void setATIME(uint8_t atime)     { as7341_.setATIME(atime); }
  void setASTEP(uint16_t astep)    { as7341_.setASTEP(astep); }

  void abort() { /* no-op: task will finish or watchdog will reset */ }

  Adafruit_AS7341 &as7341() { return as7341_; }

 private:
  // ---------------------------------------------------------------------------
  // FreeRTOS task: does the blocking read and gives the semaphore on completion.
  // ---------------------------------------------------------------------------
  struct ReadCtx {
    SpectralSensor*  sensor;
    SpectralReading* result;
    bool             success;
  };

  static void readTask_(void* arg) {
    ReadCtx* ctx = static_cast<ReadCtx*>(arg);
    SpectralSensor* self = ctx->sensor;

    if (self->as7341_.readAllChannels()) {
      SpectralReading& r = *ctx->result;
      r.f1_415nm = self->as7341_.getChannel(AS7341_CHANNEL_415nm_F1);
      r.f2_445nm = self->as7341_.getChannel(AS7341_CHANNEL_445nm_F2);
      r.f3_480nm = self->as7341_.getChannel(AS7341_CHANNEL_480nm_F3);
      r.f4_515nm = self->as7341_.getChannel(AS7341_CHANNEL_515nm_F4);
      r.f5_555nm = self->as7341_.getChannel(AS7341_CHANNEL_555nm_F5);
      r.f6_590nm = self->as7341_.getChannel(AS7341_CHANNEL_590nm_F6);
      r.f7_630nm = self->as7341_.getChannel(AS7341_CHANNEL_630nm_F7);
      r.f8_680nm = self->as7341_.getChannel(AS7341_CHANNEL_680nm_F8);
      r.clear    = self->as7341_.getChannel(AS7341_CHANNEL_CLEAR);
      r.nir      = self->as7341_.getChannel(AS7341_CHANNEL_NIR);
      ctx->success = true;
    }

    xSemaphoreGive(self->sem_);
    vTaskDelete(nullptr);  // self-delete
  }

  // ---------------------------------------------------------------------------
  // Layer 2: I2C bus recovery — unstick SDA by clocking SCL 9 times, then
  // reinitialise Wire. Called after every read failure.
  // ---------------------------------------------------------------------------
  void recoverI2C_() {
    Wire.end();
    // Manually bit-bang 9 SCL pulses. Any slave holding SDA low will release
    // it within 9 clocks (worst case: mid-byte on the last bit).
    int sclPin = SCL;
    int sdaPin = SDA;
    pinMode(sclPin, OUTPUT);
    pinMode(sdaPin, INPUT_PULLUP);
    for (int i = 0; i < 9; ++i) {
      digitalWrite(sclPin, HIGH); delayMicroseconds(5);
      digitalWrite(sclPin, LOW);  delayMicroseconds(5);
    }
    // Send a STOP condition (SDA goes HIGH while SCL is HIGH).
    digitalWrite(sclPin, HIGH); delayMicroseconds(5);
    pinMode(sdaPin, OUTPUT);
    digitalWrite(sdaPin, HIGH); delayMicroseconds(5);
    // Re-initialise Wire.
    Wire.begin();
    Wire.setClock(100000);
    Wire.setTimeOut(50);
  }

  // ---------------------------------------------------------------------------
  // Layer 1: circuit breaker — trip after FAIL_THRESHOLD consecutive failures.
  // ---------------------------------------------------------------------------
  void onFailure_() {
    recoverI2C_();
    if (++failCount_ >= FAIL_THRESHOLD) {
      ready_ = false;  // trip: further reads skipped until tryReconnect()
    }
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  uint8_t           addr_;
  Adafruit_AS7341   as7341_;
  bool              ready_          = false;
  uint8_t           failCount_      = 0;
  SemaphoreHandle_t sem_            = nullptr;
  ReadCtx           readCtx_        = {};
  bool              readInProgress_ = false;
  uint32_t          readDeadlineMs_ = 0;
  TaskHandle_t      taskHandle_     = nullptr;
};

}  // namespace components

#endif
