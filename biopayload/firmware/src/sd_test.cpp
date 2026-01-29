/**
 * BioPayload Firmware - SD Card Test
 * 
 * Tests if SD card reader is connected and working.
 * 
 * Wiring (MicroSD to Nano):
 *   5V  -> 5V
 *   GND -> GND
 *   CLK -> D13
 *   DO  -> D12 (MISO)
 *   DI  -> D11 (MOSI)
 *   CS  -> D10
 * 
 * To use: Rename this file to main.cpp (backup original first)
 */

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// Pin definitions matching your wiring
const int SD_CS_PIN = 10;   // Chip Select on D10
const int LED_PIN = LED_BUILTIN;

bool sdCardPresent = false;

void blinkLED(int times, int delayMs);
bool checkSDCard();

void setup() {
    Serial.begin(115200);
    pinMode(LED_PIN, OUTPUT);
    
    // Wait for serial connection
    delay(1000);
    
    Serial.println("=== SD Card Detection Test ===");
    Serial.println();
    Serial.println("Pin Configuration:");
    Serial.println("  CS  -> D10");
    Serial.println("  DI  -> D11 (MOSI)");
    Serial.println("  DO  -> D12 (MISO)");
    Serial.println("  CLK -> D13");
    Serial.println();
    
    // Check SD card
    Serial.println("Checking for SD card...");
    sdCardPresent = checkSDCard();
    
    if (sdCardPresent) {
        Serial.println("SUCCESS: SD card detected!");
        blinkLED(3, 200);  // 3 fast blinks = success
    } else {
        Serial.println("FAILED: SD card not detected");
        Serial.println();
        Serial.println("Troubleshooting:");
        Serial.println("  - Check wiring connections");
        Serial.println("  - Ensure SD card is inserted");
        Serial.println("  - Try a different SD card");
        Serial.println("  - Check if module has 5V or 3.3V logic");
        blinkLED(1, 1000);  // 1 long blink = failure
    }
    
    Serial.println();
    Serial.println("Send 'CHECK' to re-test SD card");
    Serial.println("Send 'INFO' to show card info (if present)");
}

void loop() {
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        cmd.toUpperCase();
        
        if (cmd == "CHECK") {
            Serial.println();
            Serial.println("Re-checking SD card...");
            
            // End previous SD session if any
            SD.end();
            delay(100);
            
            sdCardPresent = checkSDCard();
            
            if (sdCardPresent) {
                Serial.println("SUCCESS: SD card detected!");
                blinkLED(3, 200);
            } else {
                Serial.println("FAILED: SD card not detected");
                blinkLED(1, 1000);
            }
        }
        else if (cmd == "INFO") {
            if (!sdCardPresent) {
                Serial.println("No SD card present. Run CHECK first.");
            } else {
                Serial.println();
                Serial.println("=== SD Card Info ===");
                Serial.println("Card is initialized and ready");
                Serial.println("Use WRITE to test writing");
                Serial.println("Use READ to test reading");
            }
        }
        else if (cmd == "WRITE") {
            if (!sdCardPresent) {
                Serial.println("No SD card present. Run CHECK first.");
            } else {
                Serial.println("Testing write...");
                File testFile = SD.open("test.txt", FILE_WRITE);
                if (testFile) {
                    testFile.println("BioPayload SD Test");
                    testFile.close();
                    Serial.println("SUCCESS: Wrote to test.txt");
                } else {
                    Serial.println("FAILED: Could not create file");
                }
            }
        }
        else if (cmd == "READ") {
            if (!sdCardPresent) {
                Serial.println("No SD card present. Run CHECK first.");
            } else {
                Serial.println("Testing read...");
                File testFile = SD.open("test.txt", FILE_READ);
                if (testFile) {
                    Serial.println("Contents of test.txt:");
                    while (testFile.available()) {
                        Serial.write(testFile.read());
                    }
                    testFile.close();
                } else {
                    Serial.println("FAILED: Could not open test.txt");
                }
            }
        }
        else {
            Serial.println("Commands: CHECK, INFO, WRITE, READ");
        }
    }
}

bool checkSDCard() {
    // Attempt to initialize SD card
    if (SD.begin(SD_CS_PIN)) {
        return true;
    }
    return false;
}

void blinkLED(int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(delayMs);
        digitalWrite(LED_PIN, LOW);
        delay(delayMs);
    }
}
