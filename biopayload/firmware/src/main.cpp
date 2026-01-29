/**
 * BioPayload Firmware - MVP with SD Card Logging
 * 
 * Features:
 *   - Serial command protocol (HELLO, SET_CONFIG, START, ABORT, PING)
 *   - Telemetry logging to SD card in CSV format
 *   - State machine: IDLE -> RUNNING -> DONE
 * 
 * SD Card Wiring (MicroSD to Nano):
 *   5V  -> 5V
 *   GND -> GND
 *   CLK -> D13
 *   DO  -> D12 (MISO)
 *   DI  -> D11 (MOSI)
 *   CS  -> D10
 */

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// Pin definitions
const int SD_CS_PIN = 10;
const int LED_PIN = LED_BUILTIN;  // Pin 13 on Nano
const unsigned long BLINK_DELAY = 200;

// State machine
enum PayloadState { IDLE, RUNNING, DONE, ERROR_STATE };
PayloadState currentState = IDLE;

// SD card status
bool sdCardReady = false;
File logFile;
String currentRunId = "";

// Input buffer
String inputBuffer = "";

// Forward declarations
void processCommand(String cmd);
void blinkLED(unsigned long inter, int count);
bool initSDCard();
void startLogging(String runId);
void logTelemetry(unsigned long t_ms, float temp_c, int sensor, int challenge_i);
void stopLogging();

void setup() {
    Serial.begin(115200);
    pinMode(LED_PIN, OUTPUT);
    
    // Initialize SD card
    sdCardReady = initSDCard();
    if (sdCardReady) {
        Serial.println("INFO SD_READY");
    } else {
        Serial.println("INFO SD_NOT_FOUND");
    }
    
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
    else if (cmd == "SD_STATUS") {
        if (sdCardReady) {
            Serial.println("ACK SD_STATUS READY");
        } else {
            Serial.println("ACK SD_STATUS NOT_FOUND");
        }
    }
    else if (cmd.startsWith("SET_CONFIG")) {
        if (currentState != IDLE) {
            Serial.println("ERR {\"code\":\"INVALID_STATE\",\"message\":\"Must be IDLE\"}");
            return;
        }
        // For now, just acknowledge
        Serial.println("ACK SET_CONFIG");
    }
    else if (cmd == "START") {
        if (currentState != IDLE) {
            Serial.println("ERR {\"code\":\"INVALID_STATE\",\"message\":\"Must be IDLE to START\"}");
            return;
        }
        
        currentState = RUNNING;
        blinkLED(BLINK_DELAY, 2);
        Serial.println("ACK START");
        Serial.println("STATE RUNNING");
        
        // Generate run ID from millis (in real system, would come from config)
        currentRunId = String(millis());
        
        // Start SD logging
        if (sdCardReady) {
            startLogging(currentRunId);
        }
        
        // Run experiment - send telemetry messages
        unsigned long startTime = millis();
        for (int i = 0; i < 5; i++) {
            unsigned long t_ms = millis() - startTime;
            float temp = 22.0 + i * 0.5;
            int sensor = 800 + random(50);
            int challenge = i + 1;
            
            // Log to SD card
            if (sdCardReady && logFile) {
                logTelemetry(t_ms, temp, sensor, challenge);
            }
            
            // Send to serial
            Serial.print("TELEM {\"t_ms\":");
            Serial.print(t_ms);
            Serial.print(",\"temp\":");
            Serial.print(temp);
            Serial.print(",\"sensor\":");
            Serial.print(sensor);
            Serial.print(",\"challenge\":");
            Serial.print(challenge);
            Serial.println("}");
            
            delay(500);
        }
        
        // Stop logging
        if (sdCardReady) {
            stopLogging();
        }
        
        currentState = DONE;
        Serial.println("STATE DONE");
        blinkLED(BLINK_DELAY, 1);
        
        // Return to IDLE after completion
        currentState = IDLE;
        Serial.println("STATE IDLE");
    }
    else if (cmd == "ABORT") {
        if (sdCardReady && logFile) {
            logFile.println("# ABORTED");
            stopLogging();
        }
        currentState = IDLE;
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

// ============== SD Card Functions ==============

bool initSDCard() {
    if (SD.begin(SD_CS_PIN)) {
        return true;
    }
    return false;
}

void startLogging(String runId) {
    // Create filename: RUN_xxxxx.csv (8.3 format for compatibility)
    // Use last 5 digits of runId to keep filename short
    String filename = "R" + runId.substring(max(0, (int)runId.length() - 5)) + ".csv";
    
    logFile = SD.open(filename.c_str(), FILE_WRITE);
    
    if (logFile) {
        // Write CSV header
        logFile.println("t_ms,temp_c,sensor,challenge");
        logFile.flush();
        Serial.print("INFO LOG_STARTED ");
        Serial.println(filename);
    } else {
        Serial.println("ERR {\"code\":\"SD_WRITE_FAIL\",\"message\":\"Could not create log file\"}");
    }
}

void logTelemetry(unsigned long t_ms, float temp_c, int sensor, int challenge_i) {
    if (!logFile) return;
    
    // Write CSV row
    logFile.print(t_ms);
    logFile.print(",");
    logFile.print(temp_c, 2);  // 2 decimal places
    logFile.print(",");
    logFile.print(sensor);
    logFile.print(",");
    logFile.println(challenge_i);
    
    // Flush periodically to ensure data is written
    logFile.flush();
}

void stopLogging() {
    if (logFile) {
        logFile.close();
        Serial.println("INFO LOG_CLOSED");
    }
}