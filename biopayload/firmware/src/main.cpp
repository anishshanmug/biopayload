/**
 * BioPayload Firmware - Minimal Test Version
 * 
 * Responds to HELLO command to verify serial connectivity.
 * This will be expanded to full protocol later.
 */

 #include <Arduino.h>

// Forward declarations
void processCommand(String cmd);
void blinkLED(unsigned long inter, int count);
String inputBuffer = "";
const int LED_PIN = LED_BUILTIN;  // Pin 13 on Nano
 
const unsigned long BLINK_DELAY = 200;
 
 void setup() {
     Serial.begin(115200);
     pinMode(LED_PIN, OUTPUT);
     
     blinkLED(BLINK_DELAY, 3); // Blink 3 times to show IDLE
     
     // Ready message
     Serial.println("STATE IDLE");
 }
 
 void loop() {
     // Read incoming serial data
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
 
 void processCommand(String cmd) {
     cmd.trim();
     
     if (cmd == "HELLO") {
         digitalWrite(LED_PIN, HIGH);
         Serial.println("ACK HELLO");
         delay(50);
         digitalWrite(LED_PIN, LOW);
     } 
     else if (cmd == "PING") {
         Serial.println("ACK PING");
     }
     else if (cmd.startsWith("SET_CONFIG")) {
         // For now, just acknowledge
         Serial.println("ACK SET_CONFIG");
     }
     else if (cmd == "START") {
         blinkLED(BLINK_DELAY, 2); // Blink 3 times to show RUNNING
         Serial.println("ACK START");
         Serial.println("STATE RUNNING");
         // Send a few test telemetry messages
         for (int i = 0; i < 5; i++) {
             Serial.print("TELEM {\"temp\":");
             Serial.print(22.0 + i * 0.5);
             Serial.print(",\"challenge\":");
             Serial.print(i + 1);
             Serial.println("}");
             delay(500);
         }
 
         Serial.println("STATE DONE");
         blinkLED(BLINK_DELAY, 1); // Blink 3 times to show DONE
     }
     else if (cmd == "ABORT") {
         Serial.println("ACK ABORT");
         Serial.println("STATE IDLE");
     }
     else {
         Serial.print("ERR {\"code\":\"UNKNOWN_CMD\",\"message\":\"");
         Serial.print(cmd);
         Serial.println("\"}");
     }
 }
 
void blinkLED(unsigned long inter, int count) {
    for (int i = 0; i < count; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(inter);
        digitalWrite(LED_PIN, LOW);
        delay(inter);
    }
}