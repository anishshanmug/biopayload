/**
 * OD600 test with stepper - Arduino Nano ESP32
 *
 * Red LED backlight + AS7341 590nm channel for OD measurement.
 * Stepper runs continuously, controlled by single-char commands.
 *
 * Pins:
 *   RGB LED:  R=A1, G=A0, B=A2
 *   AS7341:   SDA=A4, SCL=A5
 *   Stepper:  STEP=4, DIR=2, EN=3  (raw GPIO numbers)
 *
 * Serial commands (single character):
 *   r  - reverse direction
 *   p  - pause / resume stepper
 *
 * Build & upload:
 *   pio run -e component_dev -t upload
 */

#include <Arduino.h>
#include "components/spectral_sensor.h"

static const uint32_t SERIAL_BAUD = 115200;

// RGB LED
static const int PIN_LED_R = A1;
static const int PIN_LED_G = A0;
static const int PIN_LED_B = A2;

// Stepper (raw GPIO numbers, same as working Arduino IDE sketch)
static const int PIN_STEP = 4;
static const int PIN_DIR  = 2;
static const int PIN_EN   = 3;
static const unsigned long STEP_INTERVAL_US = 120;

// Stepper state
bool stepperPaused  = true;
bool stepperForward = true;
unsigned long lastStepUs = 0;

// Sensor
components::SpectralSensor gSpecSensor;
static unsigned long lastSpecReadMs = 0;
static const unsigned long SPEC_INTERVAL_MS = 150;
static bool sensorReadingStarted = false;

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);

  // LED - red for OD600
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  digitalWrite(PIN_LED_R, HIGH);
  digitalWrite(PIN_LED_G, LOW);
  digitalWrite(PIN_LED_B, LOW);

  // Stepper
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR, OUTPUT);
  pinMode(PIN_EN, OUTPUT);
  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_DIR, HIGH);
  digitalWrite(PIN_EN, LOW);

  // Sensor
  if (gSpecSensor.begin()) {
    gSpecSensor.setATIME(29);
    gSpecSensor.setASTEP(599);
    gSpecSensor.setGain(AS7341_GAIN_64X);
    Serial.println("AS7341 OK");
  } else {
    Serial.println("AS7341 FAIL (check I2C wiring)");
  }

  Serial.println("OD600 + stepper");
  Serial.println("  r = reverse   p = pause/resume");
}

void loop() {
  // Single-char commands
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == 'r' || c == 'R') {
      stepperForward = !stepperForward;
      digitalWrite(PIN_DIR, stepperForward ? HIGH : LOW);
      Serial.println(stepperForward ? "DIR: forward" : "DIR: reverse");
    } else if (c == 'p' || c == 'P') {
      stepperPaused = !stepperPaused;
      Serial.println(stepperPaused ? "PAUSED" : "RUNNING");
    }
  }

  // Stepper (non-blocking)
  if (!stepperPaused) {
    unsigned long now = micros();
    if ((unsigned long)(now - lastStepUs) >= STEP_INTERVAL_US) {
      lastStepUs = now;
      digitalWrite(PIN_STEP, HIGH);
      delayMicroseconds(1);
      digitalWrite(PIN_STEP, LOW);
    }
  }

  // Sensor read - non-blocking using startReading/checkReadingProgress
  if (gSpecSensor.isReady()) {
    unsigned long now = millis();
    if (!sensorReadingStarted && (now - lastSpecReadMs >= SPEC_INTERVAL_MS)) {
      // Kick off a new measurement
      gSpecSensor.as7341().startReading();
      sensorReadingStarted = true;
    }
    if (sensorReadingStarted && gSpecSensor.as7341().checkReadingProgress()) {
      // Measurement complete - collect results
      components::SpectralReading r;
      r.f1_415nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_415nm_F1);
      r.f2_445nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_445nm_F2);
      r.f3_480nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_480nm_F3);
      r.f4_515nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_515nm_F4);
      r.f5_555nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_555nm_F5);
      r.f6_590nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_590nm_F6);
      r.f7_630nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_630nm_F7);
      r.f8_680nm = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_680nm_F8);
      r.clear    = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_CLEAR);
      r.nir      = gSpecSensor.as7341().getChannel(AS7341_CHANNEL_NIR);
      components::SpectralSensor::printReading(r);
      sensorReadingStarted = false;
      lastSpecReadMs = millis();
    }
  }
}
