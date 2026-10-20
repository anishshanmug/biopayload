#include "state/experiment.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <stdio.h>
#include <string.h>

#include "command/protocol.h"
#include "components/components.h"
#include "state/sd_logger.h"
#include "state/state_machine.h"

namespace biopayload {
namespace experiment {

// ---------------------------------------------------------------------------
// Runtime state
// ---------------------------------------------------------------------------
//
// The runtime is a flat state machine layered on top of the firmware-wide
// StateMachine: each top-level state (PRIMING / ACTIVE / SCANNING / DONE)
// owns its own tick handler and calls `stateMachine.transitionTo()` directly
// when it decides to advance. SCANNING in addition has an inner sub-state
// (`ScanStep`) that walks each well through HOMING -> MOVING -> SETTLING ->
// READING -> ADVANCE.
//
// All interaction with hardware goes through the components singletons so the
// runtime is testable on a bare ESP32 (most calls become "set GPIO + tick"
// without affecting program correctness).
namespace {

constexpr uint32_t MAX_PRIME_PUMP_MS  = 600000;     // 10 min sanity cap
constexpr uint32_t MAX_DURATION_MS    = 86400000;   // 24 h sanity cap
constexpr uint32_t MAX_EVERY_MS       = 86400000;
constexpr uint16_t MAX_SETTLE_MS      = 60000;
constexpr long     MAX_STEPS_FROM_HOME = 1000000L;

enum class ScanStep : uint8_t {
  IDLE     = 0,
  HOMING   = 1,
  MOVING   = 2,
  SETTLING = 3,
  READING  = 4,
  ADVANCE  = 5,
};

bool             g_hasConfig        = false;
ExperimentConfig g_cfg              = {};
uint32_t         g_activeStartMs    = 0;
ScanStep         g_scanStep         = ScanStep::IDLE;
uint8_t          g_scanWellIdx      = 0;
uint32_t         g_settleStartMs    = 0;
uint16_t         g_scansThisRun     = 0;
uint16_t         g_wellReadsThisRun = 0;
uint32_t         g_runStartMs       = 0;
bool             g_needScanInit     = false;

void writeErr(char* err, size_t errSize, const char* field) {
  if (!err || errSize == 0) return;
  strncpy(err, field, errSize - 1);
  err[errSize - 1] = '\0';
}

// ---------------------------------------------------------------------------
// JSON parsing
// ---------------------------------------------------------------------------

bool parseScheduledArray(JsonArrayConst arr, ExperimentConfig& cfg, char* err, size_t errSize) {
  cfg.scheduledCount = 0;
  if (arr.isNull()) return true;
  if (arr.size() > EXPERIMENT_MAX_SCHEDULED) {
    writeErr(err, errSize, "SCHEDULED_COUNT");
    return false;
  }
  for (JsonObjectConst entry : arr) {
    if (entry.isNull()) {
      writeErr(err, errSize, "SCHEDULED_ENTRY");
      return false;
    }
    ScheduledAction& s = cfg.scheduled[cfg.scheduledCount];

    const char* cmdStr = entry["cmd"] | "";
    if (strcmp(cmdStr, "DISPENSE") == 0) {
      s.cmd = ScheduledAction::Cmd::DISPENSE;
    } else if (strcmp(cmdStr, "SCAN_ALL_WELLS") == 0) {
      s.cmd = ScheduledAction::Cmd::SCAN_ALL_WELLS;
    } else {
      writeErr(err, errSize, "SCHEDULED_CMD");
      return false;
    }

    uint32_t every = entry["every_ms"] | 0u;
    if (every == 0u || every > MAX_EVERY_MS) {
      writeErr(err, errSize, "SCHEDULED_EVERY_MS");
      return false;
    }
    s.everyMs = every;

    if (s.cmd == ScheduledAction::Cmd::DISPENSE) {
      uint32_t pump = entry["pump_ms"] | 0u;
      if (pump == 0u || pump > MAX_PRIME_PUMP_MS) {
        writeErr(err, errSize, "SCHEDULED_PUMP_MS");
        return false;
      }
      s.pumpMs = pump;
    } else {
      s.pumpMs = 0;
    }

    s.lastFiredMs = 0;
    cfg.scheduledCount++;
  }
  return true;
}

bool parseWellsArray(JsonArrayConst arr, ExperimentConfig& cfg, char* err, size_t errSize) {
  cfg.wellCount = 0;
  if (arr.isNull()) return true;
  if (arr.size() > EXPERIMENT_MAX_WELLS) {
    writeErr(err, errSize, "WELLS_COUNT");
    return false;
  }
  for (JsonObjectConst w : arr) {
    if (w.isNull()) {
      writeErr(err, errSize, "WELL_ENTRY");
      return false;
    }
    WellSpec& ws = cfg.wells[cfg.wellCount];
    int row = w["row"] | -1;
    int col = w["col"] | -1;
    if (row < 0 || row > 7 || col < 0 || col > 11) {
      writeErr(err, errSize, "WELL_RC");
      return false;
    }
    ws.row = static_cast<uint8_t>(row);
    ws.col = static_cast<uint8_t>(col);

    long steps = w["steps_from_home"] | 0L;
    if (steps < -MAX_STEPS_FROM_HOME || steps > MAX_STEPS_FROM_HOME) {
      writeErr(err, errSize, "WELL_STEPS");
      return false;
    }
    ws.stepsFromHome = steps;

    JsonArrayConst ledArr = w["led"];
    if (ledArr.isNull() || ledArr.size() != 3) {
      writeErr(err, errSize, "WELL_LED");
      return false;
    }
    for (uint8_t i = 0; i < 3; ++i) {
      int v = ledArr[i] | -1;
      if (v < 0 || v > 255) {
        writeErr(err, errSize, "WELL_LED_RANGE");
        return false;
      }
      ws.led[i] = static_cast<uint8_t>(v);
    }
    cfg.wellCount++;
  }
  return true;
}

}  // namespace

bool parseConfig(const char* json, ExperimentConfig& cfg, char* err, size_t errSize) {
  cfg = ExperimentConfig{};
  if (err && errSize > 0) err[0] = '\0';

  if (!json || *json == '\0') {
    writeErr(err, errSize, "EMPTY");
    return false;
  }

  JsonDocument doc;
  DeserializationError jerr = deserializeJson(doc, json);
  if (jerr) {
    writeErr(err, errSize, "JSON");
    return false;
  }

  JsonObjectConst root = doc.as<JsonObjectConst>();
  if (root.isNull()) {
    writeErr(err, errSize, "ROOT");
    return false;
  }

  const char* runId = root["run_id"] | "";
  size_t runIdLen = strlen(runId);
  if (runIdLen == 0 || runIdLen >= EXPERIMENT_RUN_ID_SIZE) {
    writeErr(err, errSize, "RUN_ID");
    return false;
  }
  strncpy(cfg.runId, runId, EXPERIMENT_RUN_ID_SIZE - 1);
  cfg.runId[EXPERIMENT_RUN_ID_SIZE - 1] = '\0';

  // ------- priming -------
  JsonObjectConst priming = root["priming"];
  uint32_t primePumpMs = priming["pump_ms"] | 0u;
  if (primePumpMs > MAX_PRIME_PUMP_MS) {
    writeErr(err, errSize, "PRIME_PUMP_MS");
    return false;
  }
  cfg.primePumpMs = primePumpMs;

  // ------- active -------
  JsonObjectConst active = root["active"];
  if (active.isNull()) {
    writeErr(err, errSize, "ACTIVE");
    return false;
  }
  uint32_t durationMs = active["duration_ms"] | 0u;
  if (durationMs > MAX_DURATION_MS) {
    writeErr(err, errSize, "ACTIVE_DURATION_MS");
    return false;
  }
  cfg.activeDurationMs = durationMs;

  if (!parseScheduledArray(active["scheduled"].as<JsonArrayConst>(), cfg, err, errSize)) {
    return false;
  }

  // ------- scanning -------
  JsonObjectConst scanning = root["scanning"];
  // scanning may be entirely absent -> defaults: no wells, homing required.
  cfg.requireHoming     = scanning["homing"] | true;
  cfg.ledOffAfterRead   = scanning["led_off_after_read"] | true;
  uint32_t settle       = scanning["settle_ms"] | 0u;
  if (settle > MAX_SETTLE_MS) {
    writeErr(err, errSize, "SETTLE_MS");
    return false;
  }
  cfg.settleMs = static_cast<uint16_t>(settle);

  if (!parseWellsArray(scanning["wells"].as<JsonArrayConst>(), cfg, err, errSize)) {
    return false;
  }

  return true;
}

void storeConfig(const ExperimentConfig& cfg) {
  g_cfg       = cfg;
  g_hasConfig = true;
}

void clearConfig() {
  g_cfg       = ExperimentConfig{};
  g_hasConfig = false;
}

bool hasConfig() { return g_hasConfig; }
const ExperimentConfig& currentConfig() { return g_cfg; }

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

namespace {

// Print a quoted JSON string with a minimal escape pass on `"` and `\`.
// Used for run_id and other operator-supplied strings inside TELEM/RESULT.
void printJsonString(const char* s) {
  Serial.print('"');
  while (*s) {
    char c = *s++;
    if (c == '"' || c == '\\') Serial.print('\\');
    Serial.print(c);
  }
  Serial.print('"');
}

void emitWellTelem(uint8_t row, uint8_t col, const ::components::SpectralReading& r) {
  protocol::telemBegin();
  Serial.print(F("\"event\":\"well\",\"row\":")); Serial.print(row);
  Serial.print(F(",\"col\":")); Serial.print(col);
  Serial.print(F(",\"f1\":")); Serial.print(r.f1_415nm);
  Serial.print(F(",\"f2\":")); Serial.print(r.f2_445nm);
  Serial.print(F(",\"f3\":")); Serial.print(r.f3_480nm);
  Serial.print(F(",\"f4\":")); Serial.print(r.f4_515nm);
  Serial.print(F(",\"f5\":")); Serial.print(r.f5_555nm);
  Serial.print(F(",\"f6\":")); Serial.print(r.f6_590nm);
  Serial.print(F(",\"f7\":")); Serial.print(r.f7_630nm);
  Serial.print(F(",\"f8\":")); Serial.print(r.f8_680nm);
  Serial.print(F(",\"clear\":")); Serial.print(r.clear);
  Serial.print(F(",\"nir\":")); Serial.print(r.nir);
  protocol::telemEnd();
}

void emitResult(uint32_t now_ms, const char* status) {
  Serial.print(F("RESULT {"));
  Serial.print(F("\"run_id\":"));
  printJsonString(g_cfg.runId);
  Serial.print(F(",\"status\":"));
  printJsonString(status);
  Serial.print(F(",\"scans\":"));   Serial.print(g_scansThisRun);
  Serial.print(F(",\"wells\":"));   Serial.print(g_wellReadsThisRun);
  Serial.print(F(",\"duration_ms\":"));
  Serial.print(g_runStartMs == 0 ? 0u : (now_ms - g_runStartMs));
  Serial.println('}');
}

void resetRuntime() {
  g_activeStartMs    = 0;
  g_scanStep         = ScanStep::IDLE;
  g_scanWellIdx      = 0;
  g_settleStartMs    = 0;
  g_scansThisRun     = 0;
  g_wellReadsThisRun = 0;
  g_runStartMs       = 0;
  g_needScanInit     = false;
}

// ---------------------------------------------------------------------------
// State entry helpers
// ---------------------------------------------------------------------------

void enterDone(uint32_t now_ms, const char* status);

void enterActive(uint32_t now_ms, bool firstEntry) {
  if (firstEntry) {
    g_activeStartMs = now_ms;
    for (uint8_t i = 0; i < g_cfg.scheduledCount; ++i) {
      // Seed so the very first tick satisfies (now - last >= every), i.e.
      // scheduled actions fire immediately on the first ACTIVE tick.
      g_cfg.scheduled[i].lastFiredMs = now_ms - g_cfg.scheduled[i].everyMs;
    }
  }
  // Activedurationms == 0 with no scheduled work: nothing to do, finish.
  if (firstEntry && g_cfg.activeDurationMs == 0) {
    enterDone(now_ms, "OK");
    return;
  }
  stateMachine.transitionTo(State::ACTIVE);
}

void startScanWellMove() {
  long target = g_cfg.wells[g_scanWellIdx].stepsFromHome;
  long delta  = target - components::motor.position();
  components::motor.startMoveSteps(delta);
}

void enterScanStep(ScanStep next, uint32_t now_ms) {
  g_scanStep = next;
  switch (next) {
    case ScanStep::HOMING:
      // Re-home is currently best-effort each scan: honors requireHoming.
      components::motor.clearHomeFailed();
      components::motor.startHome(components::limit);
      break;
    case ScanStep::MOVING:
      startScanWellMove();
      break;
    case ScanStep::SETTLING:
      g_settleStartMs = now_ms;
      components::led.set(g_cfg.wells[g_scanWellIdx].led[0],
                          g_cfg.wells[g_scanWellIdx].led[1],
                          g_cfg.wells[g_scanWellIdx].led[2]);
      break;
    default:
      break;
  }
}

void enterScanning(uint32_t now_ms) {
  g_scansThisRun++;
  g_scanWellIdx = 0;
  stateMachine.transitionTo(State::SCANNING);

  if (g_cfg.wellCount == 0) {
    // Empty plate: bounce straight back to ACTIVE.
    enterActive(now_ms, false);
    return;
  }

  if (g_cfg.requireHoming) {
    enterScanStep(ScanStep::HOMING, now_ms);
  } else {
    enterScanStep(ScanStep::MOVING, now_ms);
  }
}

void enterPriming(uint32_t now_ms) {
  g_runStartMs = now_ms;
  if (g_cfg.primePumpMs == 0) {
    // No prime requested -- skip directly to ACTIVE.
    stateMachine.transitionTo(State::PRIMING);
    enterActive(now_ms, true);
    return;
  }
  components::pump.startRunForMs(g_cfg.primePumpMs);
  stateMachine.transitionTo(State::PRIMING);
}

void enterDone(uint32_t now_ms, const char* status) {
  // Drop hardware to a safe state and close the scan CSV before we tell the
  // host the run is finished.
  components::led.off();
  components::pump.off();
  components::motor.stop();
  sdLogger::endScan();

  stateMachine.transitionTo(State::DONE);
  emitResult(now_ms, status);
  // Auto-reset to IDLE so the host can immediately START another run.
  stateMachine.transitionTo(State::IDLE);
  resetRuntime();
}

void enterError(const char* code) {
  components::abortAll();
  sdLogger::endScan();
  protocol::err(code);
  stateMachine.transitionTo(State::ERROR);
  // Stay in ERROR until the operator sends ABORT.
}

// ---------------------------------------------------------------------------
// Per-state tick handlers
// ---------------------------------------------------------------------------

void tickPriming(uint32_t now_ms) {
  if (!components::pump.running()) {
    enterActive(now_ms, true);
  }
}

void fireScheduled(uint8_t i, uint32_t now_ms) {
  ScheduledAction& s = g_cfg.scheduled[i];
  s.lastFiredMs      = now_ms;
  switch (s.cmd) {
    case ScheduledAction::Cmd::DISPENSE:
      components::pump.startRunForMs(s.pumpMs);
      break;
    case ScheduledAction::Cmd::SCAN_ALL_WELLS:
      enterScanning(now_ms);
      break;
  }
}

void tickActive(uint32_t now_ms) {
  // Duration gate: if the experiment window has elapsed, finish immediately.
  // This MUST run before the scheduler so a stale scheduled action can't
  // extend the run past its configured duration.
  if (g_cfg.activeDurationMs > 0 &&
      now_ms - g_activeStartMs >= g_cfg.activeDurationMs) {
    enterDone(now_ms, "OK");
    return;
  }

  for (uint8_t i = 0; i < g_cfg.scheduledCount; ++i) {
    ScheduledAction& s = g_cfg.scheduled[i];
    if (now_ms - s.lastFiredMs >= s.everyMs) {
      fireScheduled(i, now_ms);
      if (stateMachine.current() != State::ACTIVE) return;
    }
  }
}

void tickScanning(uint32_t now_ms) {
  switch (g_scanStep) {
    case ScanStep::HOMING:
      if (components::motor.homeFailed()) {
        enterError("HOME_TIMEOUT");
        return;
      }
      if (components::motor.status() == ::components::LinearActuator::Status::IDLE &&
          components::motor.homed()) {
        enterScanStep(ScanStep::MOVING, now_ms);
      }
      break;

    case ScanStep::MOVING:
      if (components::motor.status() == ::components::LinearActuator::Status::IDLE) {
        enterScanStep(ScanStep::SETTLING, now_ms);
      }
      break;

    case ScanStep::SETTLING:
      if (now_ms - g_settleStartMs >= g_cfg.settleMs) {
        g_scanStep = ScanStep::READING;
      }
      // fall through into READING on the same tick; SPEC_READ is synchronous
      // so we may as well minimize the wire-trace gap.
      if (g_scanStep != ScanStep::READING) break;
      // intentional fallthrough
      [[fallthrough]];

    case ScanStep::READING: {
      ::components::SpectralReading r{};
      // Fall through to the read; if the AS7341 is not present we still emit a
      // TELEM record (with zeros) so the wire trace is verifiable on a bare
      // board. A real experiment should bring the sensor up before START.
      if (components::spec.isReady()) {
        components::spec.read(r);
      }
      uint8_t row = g_cfg.wells[g_scanWellIdx].row;
      uint8_t col = g_cfg.wells[g_scanWellIdx].col;
      emitWellTelem(row, col, r);
      sdLogger::logWellReading(row, col, now_ms, r);
      g_wellReadsThisRun++;
      if (g_cfg.ledOffAfterRead) components::led.off();
      g_scanStep = ScanStep::ADVANCE;
      [[fallthrough]];
    }

    case ScanStep::ADVANCE:
      g_scanWellIdx++;
      if (g_scanWellIdx >= g_cfg.wellCount) {
        enterActive(now_ms, /*firstEntry=*/false);
      } else {
        enterScanStep(ScanStep::MOVING, now_ms);
      }
      break;

    case ScanStep::IDLE:
      // Should never happen while the SM says SCANNING; treat as a bug-safe
      // recovery and drop back to ACTIVE.
      enterActive(now_ms, false);
      break;
  }
}

}  // namespace

// ---------------------------------------------------------------------------
// Public runtime API
// ---------------------------------------------------------------------------

bool start() {
  if (!g_hasConfig) return false;
  if (stateMachine.current() != State::IDLE) return false;
  resetRuntime();
  g_needScanInit = true;
  enterPriming(millis());
  return true;
}

void tick(uint32_t now_ms) {
  // Deferred SD init: beginScan() does heavy I/O (listDir, mkdir, open,
  // write header, flush) that can block for seconds. Running it here in
  // tick() — outside dispatcher::poll() — keeps the command pipeline
  // responsive so ABORT / CLEAR_CONFIG are never stuck behind SD I/O.
  if (g_needScanInit) {
    g_needScanInit = false;
    sdLogger::beginScan();
  }
  switch (stateMachine.current()) {
    case State::PRIMING:  tickPriming(now_ms);  break;
    case State::ACTIVE:   tickActive(now_ms);   break;
    case State::SCANNING: tickScanning(now_ms); break;
    case State::IDLE:
    case State::DONE:
    case State::ERROR:
      // No work in steady states. DONE is transient -- enterDone immediately
      // bounces to IDLE. ERROR sticks until ABORT.
      break;
  }
}

void onAbort() {
  resetRuntime();
}

}  // namespace experiment
}  // namespace biopayload
