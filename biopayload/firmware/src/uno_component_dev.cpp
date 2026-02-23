/**
 * Component dev – Uno (actuator board + RGB LED).
 *
 * Linear Actuator:
 *   Pins: STEP=D8, DIR=D7, EN=D9
 *   Commands: f = forward, r = reverse, s = stop
 *
 * RGB LED (potentiometer-controlled hue):
 *   Pins: R=D3, G=D5, B=D6 (PWM), POT=A1
 *   Potentiometer controls hue (0-360°), full saturation/brightness
 *
 * Build & upload:  pio run -e uno_component_dev -t upload --upload-port /dev/cu.usbmodem131201
 * Monitor:         pio device monitor --port /dev/cu.usbmodem131201
 */

#include <Arduino.h>
#include "components/linear_actuator.h"

#define SERIAL_BAUD 115200

const int POT_PIN = A1;
const int R_PIN   = 3;
const int G_PIN   = 5;
const int B_PIN   = 6;

const float POT_ALPHA = 0.35f;
const uint16_t LOOP_DELAY_MS = 8;
const float GAMMA = 2.2f;

components::LinearActuator actuator;
String inputBuffer;
float potFilt = 0.0f;

static inline uint8_t clamp8(int v) {
  if (v < 0)   return 0;
  if (v > 255) return 255;
  return (uint8_t)v;
}

uint8_t gammaCorrect(uint8_t x) {
  if (GAMMA <= 1.01f) return x;
  float xf = x / 255.0f;
  float yg = pow(xf, GAMMA);
  return (uint8_t)(yg * 255.0f + 0.5f);
}

void hsvToRgb(float h, float s, float v,
              uint8_t &r, uint8_t &g, uint8_t &b) {
  float c  = v * s;
  float hh = fmod(h, 360.0f) / 60.0f;
  float x  = c * (1.0f - fabs(fmod(hh, 2.0f) - 1.0f));
  float m  = v - c;

  float rf = 0, gf = 0, bf = 0;

  if      (0 <= hh && hh < 1) { rf = c; gf = x; bf = 0; }
  else if (1 <= hh && hh < 2) { rf = x; gf = c; bf = 0; }
  else if (2 <= hh && hh < 3) { rf = 0; gf = c; bf = x; }
  else if (3 <= hh && hh < 4) { rf = 0; gf = x; bf = c; }
  else if (4 <= hh && hh < 5) { rf = x; gf = 0; bf = c; }
  else                        { rf = c; gf = 0; bf = x; }

  r = clamp8((int)((rf + m) * 255.0f + 0.5f));
  g = clamp8((int)((gf + m) * 255.0f + 0.5f));
  b = clamp8((int)((bf + m) * 255.0f + 0.5f));
}

void applyLed(uint8_t r, uint8_t g, uint8_t b) {
  analogWrite(R_PIN, gammaCorrect(r));
  analogWrite(G_PIN, gammaCorrect(g));
  analogWrite(B_PIN, gammaCorrect(b));
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  
  pinMode(R_PIN, OUTPUT);
  pinMode(G_PIN, OUTPUT);
  pinMode(B_PIN, OUTPUT);
  
  actuator.begin();

  Serial.println("uno_component_dev ready");
  Serial.println("f = forward, r = reverse, s = stop");
  Serial.println("Pot on A1 controls RGB LED hue");
}

void loop() {
  actuator.update();

  int potRaw = analogRead(POT_PIN);
  potFilt = (1.0f - POT_ALPHA) * potFilt + POT_ALPHA * potRaw;
  
  float potNorm = constrain(potFilt / 1023.0f, 0.0f, 1.0f);
  float hue = potNorm * 359.9f;
  
  uint8_t r, g, b;
  hsvToRgb(hue, 1.0f, 1.0f, r, g, b);
  applyLed(r, g, b);

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      inputBuffer.trim();
      if (inputBuffer == "f") {
        actuator.startContinuous(true);
        Serial.println("Running forward");
      } else if (inputBuffer == "r") {
        actuator.startContinuous(false);
        Serial.println("Running reverse");
      } else if (inputBuffer == "s") {
        actuator.stop();
        Serial.println("Stopped");
      } else if (inputBuffer == "led") {
        Serial.print("Pot: "); Serial.print(potRaw);
        Serial.print(" Hue: "); Serial.print(hue, 1);
        Serial.print(" RGB: "); 
        Serial.print(r); Serial.print(",");
        Serial.print(g); Serial.print(",");
        Serial.println(b);
      } else if (inputBuffer.length() > 0) {
        Serial.print("ERR unknown: ");
        Serial.println(inputBuffer);
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  delay(LOOP_DELAY_MS);
}
