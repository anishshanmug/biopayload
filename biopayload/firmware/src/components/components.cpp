#include "components/components.h"

#include <Arduino.h>

#include "state/sd_logger.h"

namespace biopayload {
namespace components {

// ---------------------------------------------------------------------------
// Pin assignments (Arduino Nano ESP32). These match the legacy demo and the
// pin reference table in README.md. Edit here to re-pin without touching any
// component header.
// ---------------------------------------------------------------------------

namespace pins {
constexpr int PUMP = D5;

// Stepper drive: use the *silkscreen* D2 / D3 / D4 pins on the Nano ESP32.
// Do not wire to "ESP32 GPIO 2/3/4" from the S3 datasheet unless you have
// checked gpioNumberToDigitalPin -- with the default pin remap, D2→GPIO5,
// D3→GPIO6, D4→GPIO7 (see `variants/arduino_nano_nora/io_pin_remap.cpp`).
constexpr int MOTOR_STEP = D4;
constexpr int MOTOR_DIR  = D2;
constexpr int MOTOR_EN   = D3;

constexpr int LED_R = A1;
constexpr int LED_G = A0;
constexpr int LED_B = A2;

constexpr int LIMIT = D6;

// SD card: dedicated HSPI instance so it doesn't conflict with the default SPI
// bus or the I2C bus. Matches the legacy demo pinout.
constexpr int SD_CS   = D7;
constexpr int SD_CLK  = 10;   // raw GPIO 10 = HSPI SCK on this variant
constexpr int SD_MISO = D9;
constexpr int SD_MOSI = D8;
}  // namespace pins

// ---------------------------------------------------------------------------
// Singletons
// ---------------------------------------------------------------------------

::components::PeristalticPump pump (pins::PUMP);
::components::LinearActuator  motor(pins::MOTOR_STEP, pins::MOTOR_DIR, pins::MOTOR_EN);
::components::RGBLed          led  (pins::LED_R, pins::LED_G, pins::LED_B);
::components::LimitSwitch     limit(pins::LIMIT);
::components::SpectralSensor  spec;  // I2C, default address 0x39
::components::SDCard          sd(pins::SD_CS, pins::SD_CLK, pins::SD_MISO, pins::SD_MOSI);

// ---------------------------------------------------------------------------
// Boot-banner helper
// ---------------------------------------------------------------------------

namespace {

void printOk(const char* component, const char* where) {
  Serial.print(F("[boot] "));
  Serial.print(component);
  Serial.print(F(" "));
  Serial.print(where);
  Serial.println(F(" OK"));
}

void printNotFound(const char* component, const char* where) {
  Serial.print(F("[boot] "));
  Serial.print(component);
  Serial.print(F(" "));
  Serial.print(where);
  Serial.println(F(" NOT_FOUND"));
}

}  // namespace

bool beginAll() {
  // Pump (GPIO out)
  pump.begin();
  {
    char where[16];
    snprintf(where, sizeof(where), "on pin %d", pump.pin());
    printOk("pump ", where);
  }

  // Motor (GPIO out * 3)
  motor.begin();
  Serial.print(F("[boot] motor on (STEP=")); Serial.print(pins::MOTOR_STEP);
  Serial.print(F(",DIR=")); Serial.print(pins::MOTOR_DIR);
  Serial.print(F(",EN=")); Serial.print(pins::MOTOR_EN);
  Serial.println(F(") OK"));

  // RGB LED (LEDC * 3)
  led.begin();
  Serial.print(F("[boot] led   on (R=")); Serial.print(pins::LED_R);
  Serial.print(F(",G=")); Serial.print(pins::LED_G);
  Serial.print(F(",B=")); Serial.print(pins::LED_B);
  Serial.println(F(") OK"));

  // Limit switch (GPIO in, pull-up)
  limit.begin();
  Serial.print(F("[boot] limit on pin "));
  Serial.print(limit.pin());
  Serial.print(F(" "));
  Serial.println(limit.closed() ? F("CLOSED") : F("OPEN"));

  // Spectral sensor (I2C; this one has REAL presence detection)
  if (spec.begin()) {
    char where[16];
    snprintf(where, sizeof(where), "I2C 0x%02X", spec.address());
    printOk("spec ", where);
  } else {
    char where[16];
    snprintf(where, sizeof(where), "I2C 0x%02X", spec.address());
    printNotFound("spec ", where);
  }

  // SD card (HSPI; REAL presence detection -- card must be inserted)
  if (sd.begin()) {
    Serial.println(F("[boot] sd   on HSPI (CS=D7) OK"));
  } else {
    Serial.println(F("[boot] sd   on HSPI (CS=D7) NOT_FOUND"));
  }

  // Start the event logger now that the SD card has been initialised.
  // sdLogger::begin() is a no-op if the card is absent.
  biopayload::sdLogger::begin();

  return true;
}

void tickAll() {
  pump.update();
  motor.update();
  // LED, limit, spec, and sd have no async state to tick.
}

void abortAll() {
  pump.abort();
  motor.abort();
  led.abort();
  spec.abort();
  // limit is read-only; sd has no running operation to cancel.
}

}  // namespace components
}  // namespace biopayload
