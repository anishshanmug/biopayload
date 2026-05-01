#ifndef BIOPAYLOAD_SD_LOGGER_H
#define BIOPAYLOAD_SD_LOGGER_H

// SD Logger: two loggers sharing the SDCard component.
//
// EVENT LOGGER -- boot lifetime, single file `/events.log`
//   Opened once in begin() (called from components::beginAll).
//   Append-only for the entire firmware session.  Experiment boundaries
//   are marked with `--- exp NNN ---` separator lines so the file stays
//   readable across multiple power cycles.
//
//   Anyone can call sdLogger::logEvent("STATE IDLE") from anywhere in the
//   firmware. state_machine.cpp calls it on every transitionTo() and abort().
//
// SCAN DATA LOGGER -- experiment lifetime, per-experiment file
//   `/exp_001/scan.csv`, `/exp_002/scan.csv`, …
//   Opened at experiment START (beginScan), one CSV row appended + flushed
//   per well reading (logWellReading), closed at DONE/ABORT/ERROR (endScan).
//
//   If the SD card is absent, all calls are silent no-ops; the experiment
//   runtime continues without data persistence.

#include "components/spectral_sensor.h"

namespace biopayload {
namespace sdLogger {

// Initialise the event logger. Opens /events.log for append and writes a
// BOOT entry. Safe to call even if the SD card is absent (becomes a no-op).
// Called from components::beginAll() so the log is active before any commands.
void begin();

// Append a timestamped event line to /events.log.
//   T=<millis> <msg>\n
// Safe to call at any time, including from ISR-adjacent contexts. No-op if
// the event log file is not open (card absent / begin() not called).
void logEvent(const char* msg);

// ----- Scan data logger API (called by the Phase 3 experiment runtime) -----

// Open /exp_NNN/scan.csv (NNN auto-incremented) and write the CSV header.
// Also writes `--- exp NNN ---` to the event log.
// Returns the experiment id that was assigned (0 on failure).
uint16_t beginScan();

// Append one row for a completed well reading and flush.
//   timestamp_ms,row,col,f1,f2,f3,f4,f5,f6,f7,f8,clear,nir
void logWellReading(uint8_t row, uint8_t col, uint32_t timestamp_ms,
                    const ::components::SpectralReading& r);

// Close the scan CSV. Call on DONE, ABORT, and ERROR.
void endScan();

}  // namespace sdLogger
}  // namespace biopayload

#endif
