/**
 * AS7341 multi-spectral sensor test on Nano.
 * Wiring: VIN->5V or 3.3V, GND->GND, SDA->A4, SCL->A5
 *
 * Build & upload:  pio run -e nano_as7341_test -t upload
 * Monitor:         pio device monitor   (115200 baud - set in platformio.ini)
 *
 * Library: adafruit/Adafruit AS7341 in platformio.ini lib_deps.
 * On success: prints "AS7341 OK" then readings every 2s.
 * On failure: prints "AS7341 FAIL" and I2C scan.
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AS7341.h>

#define SERIAL_BAUD 115200
#define READ_INTERVAL_MS 2000
#define AS7341_I2C_ADDR 0x39

Adafruit_AS7341 as7341;
unsigned long lastReadMs = 0;
bool sensorOk = false;

void i2cScan() {
  Serial.println("I2C scan");
  int n = 0;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print("  0x");
      if (addr < 16) Serial.print("0");
      Serial.println(addr, HEX);
      n++;
    }
    delay(1);
  }
  if (n == 0) Serial.println("  (none)");
  else Serial.print("Found ");
  Serial.print(n);
  Serial.println(" device(s). AS7341 expected at 0x39");
}

void printChannels() {
  if (!as7341.readAllChannels()) {
    Serial.println("ERR read");
    return;
  }
  Serial.print("415nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_415nm_F1));
  Serial.print(" 445nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_445nm_F2));
  Serial.print(" 480nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_480nm_F3));
  Serial.print(" 515nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_515nm_F4));
  Serial.print(" 555nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_555nm_F5));
  Serial.print(" 590nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_590nm_F6));
  Serial.print(" 630nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_630nm_F7));
  Serial.print(" 680nm:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_680nm_F8));
  Serial.print(" Clear:");
  Serial.print(as7341.getChannel(AS7341_CHANNEL_CLEAR));
  Serial.print(" NIR:");
  Serial.println(as7341.getChannel(AS7341_CHANNEL_NIR));
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);

  Wire.begin();
  Wire.setClock(100000);   // 100 kHz I2C (some breakouts need standard speed)
  delay(150);

  // Explicit address and Wire port (default 0x39)
  if (!as7341.begin(AS7341_I2C_ADDR, &Wire)) {
    Serial.println("AS7341 FAIL");
    i2cScan();
    while (1) { delay(10); }
  }
  sensorOk = true;
  as7341.setATIME(100);
  as7341.setASTEP(999);
  as7341.setGain(AS7341_GAIN_256X);

  Serial.println("AS7341 OK");
  printChannels();
  lastReadMs = millis();
}

void loop() {
  unsigned long now = millis();
  if (sensorOk && (now - lastReadMs >= READ_INTERVAL_MS)) {
    lastReadMs = now;
    printChannels();
  }
  delay(10);
}
