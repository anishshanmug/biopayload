#ifndef BIOPAYLOAD_SD_CARD_H
#define BIOPAYLOAD_SD_CARD_H

// Micro-SD card via HSPI (dedicated SPI instance, avoids I2C bus conflict).
//
// Pinout (Nano ESP32 breakout, matches legacy demo):
//   CS   = D7   CLK  = 10 (raw GPIO; Nano ESP32 10 maps to SCK on HSPI)
//   MISO = D9   MOSI = D8
//
// Unlike GPIO-only components, `begin()` attempts a real SD.begin() probe --
// `present()` returns false if no card is inserted or wiring is wrong, so the
// boot banner and SYS_STATUS accurately reflect card presence.
//
// All file I/O (open, write, close) is synchronous and short (<<1 ms per call
// for small writes). There is no async update() / abort() needed.
//
// If the card is absent, all file helpers return false / invalid File objects
// and the calling loggers treat SD as gracefully degraded (experiments still
// run; logging is silently skipped).

#include <Arduino.h>
#include <FS.h>
#include <SD.h>
#include <SPI.h>

namespace components {

class SDCard {
 public:
  // Default pins match the legacy demo / AGENTS.md pinout.
  static constexpr int DEFAULT_PIN_CS   = D7;
  static constexpr int DEFAULT_PIN_CLK  = 10;
  static constexpr int DEFAULT_PIN_MISO = D9;
  static constexpr int DEFAULT_PIN_MOSI = D8;

  SDCard(int cs   = DEFAULT_PIN_CS,
         int clk  = DEFAULT_PIN_CLK,
         int miso = DEFAULT_PIN_MISO,
         int mosi = DEFAULT_PIN_MOSI)
      : cs_(cs), clk_(clk), miso_(miso), mosi_(mosi), spi_(HSPI) {}

  // Probe the card; cache result in present_. Called from beginAll().
  bool begin() {
    spi_.begin(clk_, miso_, mosi_, cs_);
    present_ = SD.begin(cs_, spi_);
    return present_;
  }

  bool present() const { return present_; }

  // Re-attempt SD.begin(). Useful if the card was inserted after boot.
  bool tryReconnect() {
    if (present_) return true;
    present_ = SD.begin(cs_, spi_);
    return present_;
  }

  // ----- Capacity -----

  uint64_t totalBytes() const {
    return present_ ? SD.totalBytes() : 0;
  }
  uint64_t usedBytes() const {
    return present_ ? SD.usedBytes() : 0;
  }

  // ----- File helpers used by the loggers -----

  // Open (or create) a file for writing from the beginning (truncates).
  File openWrite(const char* path) {
    if (!present_) return File();
    return SD.open(path, FILE_WRITE);
  }

  // Open a file for appending. Creates the file if it doesn't exist.
  File openAppend(const char* path) {
    if (!present_) return File();
    return SD.open(path, FILE_APPEND);
  }

  bool exists(const char* path) const {
    return present_ && SD.exists(path);
  }

  // Remove a single file. Returns false if absent or not ready.
  bool remove(const char* path) {
    return present_ && SD.remove(path);
  }

  // Create a directory (including intermediate components). Silent on
  // success or if it already exists.
  bool mkdir(const char* path) {
    return present_ && SD.mkdir(path);
  }

  // Iterate the entries in `dirPath`, calling `cb(name, isDir, sizeBytes)`
  // once per entry. `name` is just the filename portion, not a full path.
  // Returns false if the directory cannot be opened.
  template <typename Callback>
  bool listDir(const char* dirPath, Callback cb) {
    if (!present_) return false;
    File root = SD.open(dirPath);
    if (!root || !root.isDirectory()) return false;
    File entry = root.openNextFile();
    while (entry) {
      cb(entry.name(), entry.isDirectory(), entry.size());
      entry.close();
      entry = root.openNextFile();
    }
    root.close();
    return true;
  }

 private:
  int      cs_, clk_, miso_, mosi_;
  SPIClass spi_;
  bool     present_ = false;
};

}  // namespace components

#endif
