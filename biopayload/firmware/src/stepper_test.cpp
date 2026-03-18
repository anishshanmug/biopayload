/**
 * Interactive stepper test - Arduino Nano ESP32
 *
 * Pins:
 *   STEP: D4
 *   DIR:  D2
 *   EN:   D3
 *
 * Serial commands (single character):
 *   r  - reverse direction
 *   p  - pause / resume
 *
 * Build & upload:
 *   pio run -e stepper_test -t upload
 */

#include <Arduino.h>

static const int PIN_STEP = 4;
static const int PIN_DIR  = 2;
static const int PIN_EN   = 3;

static const unsigned long STEP_INTERVAL_US = 80;

bool paused  = false;
bool forward = true;
unsigned long lastStepUs = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR,  OUTPUT);
  pinMode(PIN_EN,   OUTPUT);

  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_DIR,  HIGH);
  digitalWrite(PIN_EN,   LOW);   // enable driver

  // Pin diagnostic: blink each pin 3 times slowly so you can probe with multimeter
  Serial.println("PIN DIAGNOSTIC: blinking EN, DIR, STEP 3x slowly...");
  for (int i = 0; i < 3; i++) {
    Serial.print("EN HIGH... "); digitalWrite(PIN_EN, HIGH); delay(500);
    Serial.println("EN LOW");    digitalWrite(PIN_EN, LOW);  delay(500);
  }
  for (int i = 0; i < 3; i++) {
    Serial.print("DIR HIGH... "); digitalWrite(PIN_DIR, HIGH); delay(500);
    Serial.println("DIR LOW");    digitalWrite(PIN_DIR, LOW);  delay(500);
  }
  for (int i = 0; i < 3; i++) {
    Serial.print("STEP HIGH... "); digitalWrite(PIN_STEP, HIGH); delay(500);
    Serial.println("STEP LOW");    digitalWrite(PIN_STEP, LOW);  delay(500);
  }
  digitalWrite(PIN_DIR, HIGH);
  digitalWrite(PIN_EN, LOW);

  Serial.println("Stepper test ready");
  Serial.println("  r = reverse   p = pause/resume");
}

void loop() {
  // Handle incoming commands (non-blocking)
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == 'r' || c == 'R') {
      forward = !forward;
      digitalWrite(PIN_DIR, forward ? HIGH : LOW);
      Serial.println(forward ? "DIR: forward" : "DIR: reverse");
    } else if (c == 'p' || c == 'P') {
      paused = !paused;
      Serial.println(paused ? "PAUSED" : "RUNNING");
    }
  }

  if (paused) return;

  // Non-blocking step using micros()
  unsigned long now = micros();
  if ((unsigned long)(now - lastStepUs) >= STEP_INTERVAL_US) {
    lastStepUs = now;
    digitalWrite(PIN_STEP, HIGH);
    delayMicroseconds(1);
    digitalWrite(PIN_STEP, LOW);
  }
}
