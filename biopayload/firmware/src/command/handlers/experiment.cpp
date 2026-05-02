// Experiment control handlers: SET_CONFIG and START.
//
//   SET_CONFIG {json}   ACK SET_CONFIG | ERR BAD_CONFIG <field>
//   CLEAR_CONFIG        ACK CLEAR_CONFIG
//   START               ACK START      | ERR NO_CONFIG | ERR BAD_STATE
//
// These two are the bridge between the host's experiment description (a JSON
// payload) and the firmware's autonomous experiment runtime. After SET_CONFIG
// validates and stores the config, START kicks the state machine into PRIMING
// and the runtime drives the rest (ACTIVE / SCANNING / DONE) without any
// further host involvement.
//
// The dispatcher's parser leaves the JSON portion of `SET_CONFIG {...}` in
// `cmd.rest` (see command/parser.h: tokenization stops at '{'), so the
// handler reads `cmd.rest` directly rather than tokenizing further.

#include <Arduino.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "state/experiment.h"
#include "state/state_machine.h"

namespace biopayload {
namespace handlers {

void hSetConfig(const ParsedCmd& cmd) {
  ExperimentConfig cfg;
  char err[EXPERIMENT_ERR_FIELD_LEN] = {0};
  if (!experiment::parseConfig(cmd.rest, cfg, err, sizeof(err))) {
    protocol::err("BAD_CONFIG", err[0] ? err : "JSON");
    return;
  }
  experiment::storeConfig(cfg);
  protocol::ack("SET_CONFIG");
}

void hClearConfig(const ParsedCmd& /*cmd*/) {
  experiment::clearConfig();
  protocol::ack("CLEAR_CONFIG");
}

void hStart(const ParsedCmd& /*cmd*/) {
  if (!experiment::hasConfig()) {
    protocol::err("NO_CONFIG");
    return;
  }
  if (stateMachine.current() != State::IDLE) {
    protocol::err("BAD_STATE", "START");
    return;
  }
  // ACK first so the host sees the start point in the trace before any STATE
  // PRIMING line that experiment::start() will emit synchronously below.
  protocol::ack("START");
  if (!experiment::start()) {
    // start() can only fail for the conditions we just checked, but be
    // defensive in case future refactors add new failure modes.
    protocol::err("START_FAIL");
  }
}

}  // namespace handlers
}  // namespace biopayload
