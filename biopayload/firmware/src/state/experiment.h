#ifndef BIOPAYLOAD_STATE_EXPERIMENT_H
#define BIOPAYLOAD_STATE_EXPERIMENT_H

// Phase 3 -- experiment runtime + config.
//
// Layout overview:
//
//   ExperimentConfig                  -- the full set of parameters needed to
//                                        run one experiment, populated by
//                                        parseConfig() from a JSON payload sent
//                                        with `SET_CONFIG`.
//   experiment::parseConfig(json,..)  -- ArduinoJson-backed validator. Returns
//                                        false + writes a short field name to
//                                        `err` on malformed / out-of-range
//                                        input so SET_CONFIG can answer with
//                                        `ERR BAD_CONFIG <field>`.
//   experiment::storeConfig(cfg)      -- copies into the static slot owned by
//                                        the runtime. Persists across an
//                                        ABORT, but NOT across a reset.
//   experiment::start()               -- entry point for the START handler.
//                                        Validates IDLE + config presence,
//                                        then drives the state machine into
//                                        PRIMING and kicks off the prime pump.
//   experiment::tick(now_ms)          -- called every loop() from
//                                        StateMachine::tick. Drives the
//                                        PRIMING / ACTIVE / SCANNING / DONE
//                                        sub-state-machines.
//   experiment::onAbort()             -- called from StateMachine::abort.
//                                        Resets the runtime's internal cursors
//                                        but keeps `hasConfig()` so the
//                                        operator can re-issue START without
//                                        re-uploading the config.
//
// JSON shape parsed by parseConfig (see COMMAND_REFERENCE.md for the contract):
//
//   {
//     "run_id": "demo-001",
//     "priming": { "pump_ms": 1000 },
//     "active": {
//       "duration_ms": 8000,
//       "scheduled": [
//         { "cmd": "DISPENSE",       "every_ms": 4000, "pump_ms": 500 },
//         { "cmd": "SCAN_ALL_WELLS", "every_ms": 3000 }
//       ]
//     },
//     "scanning": {
//       "homing": false,
//       "settle_ms": 200,
//       "led_off_after_read": true,
//       "wells": [
//         { "row": 0, "col": 0, "steps_from_home": 0,    "led": [255, 0, 0] },
//         { "row": 0, "col": 1, "steps_from_home": 100,  "led": [255, 0, 0] }
//       ]
//     }
//   }
//
// All durations / intervals are in milliseconds. `homing` defaults to true;
// set it to false in bare-board / pre-wiring tests so SCANNING does not need a
// real limit switch.

#include <stddef.h>
#include <stdint.h>

namespace biopayload {

constexpr uint8_t  EXPERIMENT_MAX_WELLS     = 12;
constexpr uint8_t  EXPERIMENT_MAX_SCHEDULED = 4;
constexpr uint8_t  EXPERIMENT_RUN_ID_SIZE   = 32;
constexpr size_t   EXPERIMENT_ERR_FIELD_LEN = 32;

struct WellSpec {
  uint8_t row;
  uint8_t col;
  long    stepsFromHome;
  uint8_t led[3];
};

struct ScheduledAction {
  enum class Cmd : uint8_t { DISPENSE = 0, SCAN_ALL_WELLS = 1 };

  Cmd      cmd          = Cmd::DISPENSE;
  uint32_t everyMs      = 0;
  uint32_t pumpMs       = 0;   // DISPENSE only
  uint32_t lastFiredMs  = 0;   // runtime-managed
};

struct ExperimentConfig {
  char     runId[EXPERIMENT_RUN_ID_SIZE] = {0};
  uint32_t primePumpMs                   = 0;
  uint32_t activeDurationMs              = 0;
  uint16_t settleMs                      = 0;
  bool     ledOffAfterRead               = true;
  bool     requireHoming                 = true;

  ScheduledAction scheduled[EXPERIMENT_MAX_SCHEDULED] = {};
  uint8_t         scheduledCount                       = 0;

  WellSpec wells[EXPERIMENT_MAX_WELLS] = {};
  uint8_t  wellCount                   = 0;
};

namespace experiment {

// Parse `json` into `cfg`. Returns true on success. On failure, writes a short
// `<field>` name into `err` (no-op if `err` is null) so the caller can emit
// `ERR BAD_CONFIG <field>`. Common error tokens: `JSON`, `RUN_ID`,
// `ACTIVE`, `SCHEDULED`, `WELLS`, `WELL_LED`, etc.
bool parseConfig(const char* json,
                 ExperimentConfig& cfg,
                 char* err,
                 size_t errSize);

// Replace the runtime's stored config. Persists until clearConfig() / reset.
void storeConfig(const ExperimentConfig& cfg);
void clearConfig();
bool hasConfig();
const ExperimentConfig& currentConfig();

// Kick off a run. Returns false if no config has been stored. Caller is
// responsible for ensuring the state machine is in IDLE.
bool start();

// Loop driver. Called from StateMachine::tick() every iteration with the
// current `millis()` value.
void tick(uint32_t now_ms);

// Wipe runtime cursors / sub-state on ABORT. Keeps the stored config so a
// follow-up START re-runs the same experiment.
void onAbort();

}  // namespace experiment
}  // namespace biopayload

#endif
