// Pump command handlers.
//
//   PUMP_RUN <ms>   ACK PUMP_RUN     (then DONE PUMP_RUN once `ms` elapses)
//   PUMP_ON         ACK PUMP_ON
//   PUMP_OFF        ACK PUMP_OFF
//   PUMP_STATUS     PUMP_STATUS RUNNING|IDLE
//
// The async DONE for PUMP_RUN is wired through the dispatcher's pending-DONE
// tracker. The check just polls `pump.running()`; the pump's update() (called
// from components::tickAll()) is what actually flips that flag.

#include <Arduino.h>

#include "command/dispatcher.h"
#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

namespace {

dispatcher::DoneResult pumpIdle(void* ctx) {
  auto* p = static_cast<::components::PeristalticPump*>(ctx);
  return p->running() ? dispatcher::DoneResult::PENDING
                      : dispatcher::DoneResult::DONE;
}

}  // namespace

void hPumpRun(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "PUMP_RUN <ms>");
    return;
  }
  long ms;
  if (!parseLong(cmd.argv[0], &ms) || ms < 0) {
    protocol::err("BAD_ARG", cmd.argv[0]);
    return;
  }
  protocol::ack("PUMP_RUN");
  components::pump.startRunForMs(static_cast<unsigned long>(ms));
  // PUMP_RUN 0 leaves the pump idle; the pending check returns DONE on the
  // next poll, which is the contract we want (immediate DONE).
  dispatcher::registerPending("PUMP_RUN", &pumpIdle, &components::pump);
}

void hPumpOn(const ParsedCmd&) {
  components::pump.on();
  protocol::ack("PUMP_ON");
}

void hPumpOff(const ParsedCmd&) {
  components::pump.off();
  protocol::ack("PUMP_OFF");
}

void hPumpStatus(const ParsedCmd&) {
  Serial.print(F("PUMP_STATUS "));
  Serial.println(components::pump.running() ? F("RUNNING") : F("IDLE"));
}

}  // namespace handlers
}  // namespace biopayload
