/**
 * Component dev – Nano (pump + spectral sensor + RGB LED).
 *
 * RGB LED: Two modes:
 *   - POT mode (default): Potentiometer on A1 controls hue (0-360°)
 *   - AUTO mode: LED oscillates through full color spectrum
 *   Pins: R=D3, G=D5, B=D6 (PWM), POT=A1
 *
 * Build & upload:  pio run -e nano_component_dev -t upload --upload-port /dev/cu.usbserial-13110
 * Monitor:         pio device monitor --port /dev/cu.usbserial-13110
 *
 * Commands:
 *   PUMP <ms>    - Run pump for specified milliseconds
 *   SPEC         - Read spectral sensor
 *   LED          - Print current LED state
 *   AUTO         - Toggle between POT and AUTO mode
 *   AUTO <speed> - Set oscillation speed (0.01-10.0 deg/cycle)
 *   PING         - Health check
 *   ABORT        - Stop pump
 */

#include <Arduino.h>
#include "components/peristaltic_pump.h"
#include "components/spectral_sensor.h"

#define SERIAL_BAUD 115200
#define PIN_PUMP 9

const int POT_PIN = A1;
const int R_PIN   = 3;
const int G_PIN   = 5;
const int B_PIN   = 6;

const float POT_ALPHA = 0.35f;
const uint16_t LOOP_DELAY_MS = 8;
const float GAMMA = 2.2f;
const float DEFAULT_AUTO_SPEED = 1.0f;

components::PeristalticPump pump(PIN_PUMP);
components::SpectralSensor specSensor;
String inputBuffer;
bool pumpAckPending = false;
float potFilt = 0.0f;

bool ledAutoMode = false;
float autoHue = 0.0f;
float autoSpeed = DEFAULT_AUTO_SPEED;

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

uint8_t currentR = 0, currentG = 0, currentB = 0;
float currentHue = 0;
int currentPotRaw = 0;

void updateLed() {
  if (ledAutoMode) {
    autoHue += autoSpeed;
    if (autoHue >= 360.0f) autoHue -= 360.0f;
    if (autoHue < 0.0f) autoHue += 360.0f;
    currentHue = autoHue;
    currentPotRaw = -1;
  } else {
    currentPotRaw = analogRead(POT_PIN);
    potFilt = (1.0f - POT_ALPHA) * potFilt + POT_ALPHA * currentPotRaw;
    float potNorm = constrain(potFilt / 1023.0f, 0.0f, 1.0f);
    currentHue = potNorm * 359.9f;
  }
  
  hsvToRgb(currentHue, 1.0f, 1.0f, currentR, currentG, currentB);
  applyLed(currentR, currentG, currentB);
}

void processCommand(String cmd) {
  cmd.trim();

  if (cmd == "PING") {
    Serial.println("ACK PING");
    return;
  }

  if (cmd.startsWith("PUMP ")) {
    unsigned long ms = (unsigned long)cmd.substring(5).toInt();
    Serial.print("PUMP run ");
    Serial.print(ms);
    Serial.println(" ms");
    pump.startRunForMs(ms);
    pumpAckPending = true;
    return;
  }

  if (cmd == "SPEC") {
    if (!specSensor.isReady()) {
      Serial.println("ERR SPEC not ready");
      return;
    }
    components::SpectralReading r;
    if (specSensor.read(r)) {
      components::SpectralSensor::printReading(r);
      Serial.println("ACK SPEC");
    } else {
      Serial.println("ERR SPEC read failed");
    }
    return;
  }

  if (cmd == "LED") {
    Serial.print("LED Mode:");
    Serial.print(ledAutoMode ? "AUTO" : "POT");
    if (!ledAutoMode) {
      Serial.print(" Pot:");
      Serial.print(currentPotRaw);
    } else {
      Serial.print(" Speed:");
      Serial.print(autoSpeed, 2);
    }
    Serial.print(" Hue:");
    Serial.print(currentHue, 1);
    Serial.print(" RGB:");
    Serial.print(currentR);
    Serial.print(",");
    Serial.print(currentG);
    Serial.print(",");
    Serial.println(currentB);
    return;
  }

  if (cmd == "AUTO") {
    ledAutoMode = !ledAutoMode;
    if (ledAutoMode) {
      autoHue = currentHue;
    }
    Serial.print("LED mode: ");
    Serial.println(ledAutoMode ? "AUTO (oscillating)" : "POT (manual)");
    return;
  }

  if (cmd.startsWith("AUTO ")) {
    float speed = cmd.substring(5).toFloat();
    if (speed >= 0.01f && speed <= 10.0f) {
      autoSpeed = speed;
      Serial.print("Auto speed set to ");
      Serial.print(autoSpeed, 2);
      Serial.println(" deg/cycle");
    } else {
      Serial.println("ERR speed must be 0.01-10.0");
    }
    return;
  }

  if (cmd == "ABORT") {
    pump.abort();
    pumpAckPending = false;
    Serial.println("ACK ABORT");
    return;
  }

  Serial.print("ERR unknown: ");
  Serial.println(cmd);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);

  pinMode(R_PIN, OUTPUT);
  pinMode(G_PIN, OUTPUT);
  pinMode(B_PIN, OUTPUT);

  pump.begin();

  if (specSensor.begin()) {
    Serial.println("AS7341 OK");
  } else {
    Serial.println("AS7341 FAIL (SPEC command disabled)");
  }

  Serial.println("nano_component_dev ready");
  Serial.println("PUMP <ms> | SPEC | PING | ABORT | LED | AUTO | AUTO <speed>");
  Serial.println("Pot on A1 controls RGB LED hue (AUTO toggles oscillation)");
}

void loop() {
  pump.update();
  updateLed();

  if (pumpAckPending && !pump.running()) {
    pumpAckPending = false;
    Serial.println("ACK PUMP");
  }

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
    }
  }

  delay(LOOP_DELAY_MS);
}
