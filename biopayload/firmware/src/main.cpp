/**
 * Well-plate scan demo - Arduino Nano ESP32
 *
 * RGB LED backlight + AS7341 spectral sensor on stepper-driven linear stage.
 * Stepper translates the sensor across a well plate in 39 s.
 * During a scan the firmware averages 590 nm readings within fixed time
 * windows for each of the 4 wells (8-9 s, 18-19 s, 28-29 s, 38-39 s).
 * Results are printed over serial and flushed to SD card as CSV.
 *
 * Pins:
 *   RGB LED:   R=A1, G=A0, B=A2
 *   AS7341:    SDA=A4, SCL=A5
 *   Stepper:   STEP=4, DIR=2, EN=3  (raw GPIO numbers)
 *   Pump:      D5
 *   SD card:   CLK=10, MISO(DO)=D9, MOSI(DI)=D8, CS=D7
 *
 * Serial commands (single character):
 *   s  - start well-plate scan (39 s run)
 *   r  - reverse direction
 *   p  - pause / resume stepper
 *   m  - toggle pump on/off
 *   x  - stop stepper (abort scan if active)
 *
 * Build & upload:
 *   pio run -e component_dev -t upload
 */

 #include <Arduino.h>
 #include <SPI.h>
 #include <FS.h>
 #include <SD.h>
 #include "components/spectral_sensor.h"
 
 static const uint32_t SERIAL_BAUD = 115200;
 
 // RGB LED
 static const int PIN_LED_R = A1;
 static const int PIN_LED_G = A0;
 static const int PIN_LED_B = A2;
 
 // Stepper (raw GPIO numbers)
 static const int PIN_STEP = 4;
 static const int PIN_DIR  = 2;
 static const int PIN_EN   = 3;
 static const unsigned long STEP_INTERVAL_US = 120;
 
 // Pump
 static const int PIN_PUMP = D5;
 bool pumpOn = false;
 
 // SD card (custom SPI pins)
 static const int PIN_SD_CS   = D7;
 static const int PIN_SD_CLK  = 10;
 static const int PIN_SD_MISO = D9;
 static const int PIN_SD_MOSI = D8;
 SPIClass sdSPI(HSPI);
 bool sdReady = false;
 int scanNumber = 0;
 
 // Stepper state
 bool stepperPaused  = true;
 bool stepperForward = true;
 unsigned long lastStepUs = 0;
 
 // Sensor
 components::SpectralSensor gSpecSensor;
 static unsigned long lastSpecReadMs = 0;
 static const unsigned long SPEC_INTERVAL_MS = 150;
 static bool sensorReadingStarted = false;
 
 // ---- Scan state ----
 static const unsigned long SCAN_DURATION_MS = 39000;
 static const int NUM_WELLS = 4;
 
 // Time windows (ms) for each well — readings in this range are averaged
 static const unsigned long WELL_START_MS[NUM_WELLS] = { 8000, 17500, 27000, 36500 };
 static const unsigned long WELL_END_MS[NUM_WELLS]   = { 9000, 18500, 28000, 37500 };
 
 bool     scanActive   = false;
 unsigned long scanStartMs = 0;
 
 struct WellAccum {
   unsigned long sum;
   uint16_t count;
 };
 WellAccum wells[NUM_WELLS];
 
 static void resetWells() {
   for (int i = 0; i < NUM_WELLS; i++) {
     wells[i].sum   = 0;
     wells[i].count = 0;
   }
 }
 
 static void accumReading(uint16_t val, unsigned long elapsed) {
   for (int i = 0; i < NUM_WELLS; i++) {
     if (elapsed >= WELL_START_MS[i] && elapsed <= WELL_END_MS[i]) {
       wells[i].sum += val;
       wells[i].count++;
     }
   }
 }
 
 static void printScanResults() {
   Serial.println("SCAN_DONE");
   for (int i = 0; i < NUM_WELLS; i++) {
     uint16_t avg = wells[i].count > 0
                    ? (uint16_t)(wells[i].sum / wells[i].count)
                    : 0;
     Serial.print("WELL ");
     Serial.print(i + 1);
     Serial.print(" 590nm=");
     Serial.print(avg);
     Serial.print(" n=");
     Serial.println(wells[i].count);
   }
 }
 
 static void saveScanToSD() {
   if (!sdReady) {
     Serial.println("SD_ERR no card");
     return;
   }
   scanNumber++;
   char filename[20];
   snprintf(filename, sizeof(filename), "/scan_%03d.csv", scanNumber);
 
   File f = SD.open(filename, FILE_WRITE);
   if (!f) {
     Serial.print("SD_ERR open ");
     Serial.println(filename);
     return;
   }
 
   f.println("Well,590nm_Avg,Samples");
   for (int i = 0; i < NUM_WELLS; i++) {
     uint16_t avg = wells[i].count > 0
                    ? (uint16_t)(wells[i].sum / wells[i].count)
                    : 0;
     f.print(i + 1);
     f.print(",");
     f.print(avg);
     f.print(",");
     f.println(wells[i].count);
   }
   f.close();
 
   Serial.print("SD_OK ");
   Serial.println(filename);
 }
 
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
 
   // Pump
   pinMode(PIN_PUMP, OUTPUT);
   digitalWrite(PIN_PUMP, LOW);
 
   // SD card
   sdSPI.begin(PIN_SD_CLK, PIN_SD_MISO, PIN_SD_MOSI, PIN_SD_CS);
   if (SD.begin(PIN_SD_CS, sdSPI)) {
     sdReady = true;
     Serial.println("SD OK");
   } else {
     Serial.println("SD FAIL (check wiring/card)");
   }
 
   // Sensor
   if (gSpecSensor.begin()) {
     gSpecSensor.setATIME(29);
     gSpecSensor.setASTEP(599);
     gSpecSensor.setGain(AS7341_GAIN_64X);
     Serial.println("AS7341 OK");
   } else {
     Serial.println("AS7341 FAIL (check I2C wiring)");
   }
 
   Serial.println("Well-plate scan ready");
   Serial.println("  s=scan r=reverse p=pause m=pump x=stop");
 }
 
 void loop() {
   // Single-char commands
   while (Serial.available()) {
     char c = (char)Serial.read();
     if (c == 's' || c == 'S') {
       if (!scanActive) {
         resetWells();
         scanStartMs  = millis();
         scanActive   = true;
         stepperPaused = false;
         Serial.println("SCAN_START");
       }
     } else if (c == 'r' || c == 'R') {
       if (scanActive) {
         scanActive    = false;
         stepperPaused = true;
         Serial.println("SCAN_ABORTED");
         printScanResults();
       }
       stepperForward = !stepperForward;
       digitalWrite(PIN_DIR, stepperForward ? HIGH : LOW);
       Serial.println(stepperForward ? "DIR: forward" : "DIR: reverse");
     } else if (c == 'p' || c == 'P') {
       if (scanActive) {
         scanActive    = false;
         stepperPaused = true;
         Serial.println("SCAN_ABORTED");
         printScanResults();
       } else {
         stepperPaused = !stepperPaused;
         Serial.println(stepperPaused ? "PAUSED" : "RUNNING");
       }
     } else if (c == 'm' || c == 'M') {
       pumpOn = !pumpOn;
       digitalWrite(PIN_PUMP, pumpOn ? HIGH : LOW);
       Serial.println(pumpOn ? "PUMP_ON" : "PUMP_OFF");
     } else if (c == 'x' || c == 'X') {
       if (scanActive) {
         scanActive    = false;
         stepperPaused = true;
         Serial.println("SCAN_ABORTED");
         printScanResults();
       }
       stepperPaused = true;
       Serial.println("STOPPED");
     }
   }
 
   // Check scan timeout
   if (scanActive) {
     unsigned long elapsed = millis() - scanStartMs;
     if (elapsed >= SCAN_DURATION_MS) {
       scanActive    = false;
       stepperPaused = true;
       printScanResults();
       saveScanToSD();
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
 
   // Sensor read - non-blocking
   if (gSpecSensor.isReady()) {
     unsigned long now = millis();
     if (!sensorReadingStarted && (now - lastSpecReadMs >= SPEC_INTERVAL_MS)) {
       gSpecSensor.as7341().startReading();
       sensorReadingStarted = true;
     }
     if (sensorReadingStarted && gSpecSensor.as7341().checkReadingProgress()) {
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
 
       if (scanActive) {
         unsigned long elapsed = millis() - scanStartMs;
         accumReading(r.f6_590nm, elapsed);
         // Prefix with elapsed time so the GUI can plot against scan time
         Serial.print("SCAN T:");
         Serial.print(elapsed);
         Serial.print(" ");
       }
 
       components::SpectralSensor::printReading(r);
       sensorReadingStarted = false;
       lastSpecReadMs = millis();
     }
   }
 }
 