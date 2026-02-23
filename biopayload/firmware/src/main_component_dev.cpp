/**
 * Component dev main - minimal firmware for quick iteration.
 *
 * Build & upload:  pio run -e component_dev -t upload
 * Then open monitor: pio device monitor
 *
 * Commands (one per line):
 *   PUMP <ms>            Run peristaltic pump (e.g. PUMP 1000)
 *   ACTUATOR STEP <n> <d> Move linear actuator n steps, direction d (0 or 1)
 *   ABORT                 Stop pump and actuator immediately
 *   PING                  Check alive
 */

#include <Arduino.h>
#include "components/peristaltic_pump.h"
#include "components/linear_actuator.h"

#define SERIAL_BAUD 115200

#define PIN_PUMP           6   // Pump control (other side to GND)
#define PIN_ACTUATOR_STEP  8   // TMC2208 STEP
#define PIN_ACTUATOR_DIR   7   // TMC2208 DIR
#define PIN_ACTUATOR_EN    9   // TMC2208 ENABLE (active-LOW), or -1 if not used

components::PeristalticPump pump(PIN_PUMP);
components::LinearActuator actuator(PIN_ACTUATOR_STEP, PIN_ACTUATOR_DIR, PIN_ACTUATOR_EN);
String inputBuffer;
bool pumpAckPending = false;
bool actuatorAckPending = false;

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

  if (cmd.startsWith("ACTUATOR STEP ")) {
    int space = cmd.indexOf(' ', 14);
    if (space < 0) {
      Serial.println("ERR ACTUATOR usage: ACTUATOR STEP <steps> <dir 0|1>");
      return;
    }
    long steps = cmd.substring(14, space).toInt();
    int dir = cmd.substring(space + 1).toInt();
    if (steps <= 0) {
      Serial.println("ERR steps must be positive");
      return;
    }
    long signedSteps = (dir != 0) ? steps : -steps;
    Serial.print("ACTUATOR ");
    Serial.print(steps);
    Serial.print(" steps dir ");
    Serial.println(dir);
    actuator.startMoveSteps(signedSteps);
    actuatorAckPending = true;
    return;
  }

  if (cmd == "ABORT") {
    pump.abort();
    actuator.abort();
    pumpAckPending = false;
    actuatorAckPending = false;
    Serial.println("ACK ABORT");
    return;
  }

  Serial.print("ERR unknown: ");
  Serial.println(cmd);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  pump.begin();
  actuator.begin();

  Serial.println("component_dev ready");
  Serial.println("PUMP <ms> | ACTUATOR STEP <n> <0|1> | PING | ABORT");
}

void loop() {
  pump.update();
  actuator.update();

  if (pumpAckPending && !pump.running()) {
    pumpAckPending = false;
    Serial.println("ACK PUMP");
  }
  if (actuatorAckPending && !actuator.moving()) {
    actuatorAckPending = false;
    Serial.println("ACK ACTUATOR");
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
}
