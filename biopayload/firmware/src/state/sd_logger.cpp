#include "state/sd_logger.h"

#include <Arduino.h>
#include <FS.h>

#include "components/components.h"

namespace biopayload {
namespace sdLogger {

namespace {

File  g_eventFile;         // /events.log -- kept open for the session
File  g_scanFile;          // /exp_NNN/scan.csv -- open only during an experiment
uint16_t g_expId = 0;      // current experiment id; 0 = none open

// ---- helpers ----

// Build a next experiment id by scanning existing /exp_NNN/ directories.
uint16_t nextExpId() {
  uint16_t maxId = 0;
  components::sd.listDir("/", [&maxId](const char* name, bool isDir, size_t) {
    if (!isDir) return;
    if (name[0] == 'e' && name[1] == 'x' && name[2] == 'p' && name[3] == '_') {
      uint16_t id = static_cast<uint16_t>(atoi(name + 4));
      if (id > maxId) maxId = id;
    }
  });
  return maxId + 1;
}

void writeEventLine(const char* msg) {
  if (!g_eventFile) return;
  g_eventFile.print(F("T="));
  g_eventFile.print(millis());
  g_eventFile.print(' ');
  g_eventFile.println(msg);
  g_eventFile.flush();
}

}  // namespace

// ---------------------------------------------------------------------------
// Event logger
// ---------------------------------------------------------------------------

void begin() {
  if (!components::sd.present()) return;
  g_eventFile = components::sd.openAppend("/events.log");
  if (!g_eventFile) return;
  // Version separator so multiple boot sessions are distinguishable.
  g_eventFile.println(F("--- BOOT ---"));
  writeEventLine("BOOT 0.1.0");
}

void logEvent(const char* msg) {
  writeEventLine(msg);
}

// ---------------------------------------------------------------------------
// Scan data logger
// ---------------------------------------------------------------------------

uint16_t beginScan() {
  if (!components::sd.present()) return 0;

  g_expId = nextExpId();

  // Create /exp_NNN/ directory.
  char dir[16];
  snprintf(dir, sizeof(dir), "/exp_%03u", g_expId);
  components::sd.mkdir(dir);

  // Open the CSV file.
  char path[32];
  snprintf(path, sizeof(path), "/exp_%03u/scan.csv", g_expId);
  g_scanFile = components::sd.openWrite(path);
  if (!g_scanFile) {
    g_expId = 0;
    return 0;
  }

  // CSV header.
  g_scanFile.println(
      F("timestamp_ms,well_row,well_col,"
        "f1_415,f2_445,f3_480,f4_515,f5_555,f6_590,f7_630,f8_680,clear,nir"));
  g_scanFile.flush();

  // Event log marker.
  {
    char msg[32];
    snprintf(msg, sizeof(msg), "--- exp %03u ---", g_expId);
    writeEventLine(msg);
  }

  return g_expId;
}

void logWellReading(uint8_t row, uint8_t col, uint32_t timestamp_ms,
                    const ::components::SpectralReading& r) {
  if (!g_scanFile) return;
  g_scanFile.print(timestamp_ms);  g_scanFile.print(',');
  g_scanFile.print(row);           g_scanFile.print(',');
  g_scanFile.print(col);           g_scanFile.print(',');
  g_scanFile.print(r.f1_415nm);   g_scanFile.print(',');
  g_scanFile.print(r.f2_445nm);   g_scanFile.print(',');
  g_scanFile.print(r.f3_480nm);   g_scanFile.print(',');
  g_scanFile.print(r.f4_515nm);   g_scanFile.print(',');
  g_scanFile.print(r.f5_555nm);   g_scanFile.print(',');
  g_scanFile.print(r.f6_590nm);   g_scanFile.print(',');
  g_scanFile.print(r.f7_630nm);   g_scanFile.print(',');
  g_scanFile.print(r.f8_680nm);   g_scanFile.print(',');
  g_scanFile.print(r.clear);      g_scanFile.print(',');
  g_scanFile.println(r.nir);
  g_scanFile.flush();
}

void endScan() {
  if (g_scanFile) {
    g_scanFile.close();
  }
  if (g_expId > 0) {
    char msg[32];
    snprintf(msg, sizeof(msg), "exp %03u END", g_expId);
    writeEventLine(msg);
    g_expId = 0;
  }
}

}  // namespace sdLogger
}  // namespace biopayload
