// Linear-actuator command handlers.
//
//   MOT_MOVE <steps>     ACK MOT_MOVE        (then DONE MOT_MOVE)
//   MOT_RUN <FWD|REV>    ACK MOT_RUN         (no DONE -- continuous)
//   MOT_STOP             ACK MOT_STOP
//   MOT_HOME             ACK MOT_HOME        (then DONE MOT_HOME on switch
//                                             close, or ERR HOME_TIMEOUT
//                                             after the configured deadline)
//   MOT_POS              MOT_POS <signed_steps_from_home>
//   MOT_ENABLE           ACK MOT_ENABLE
//   MOT_DISABLE          ACK MOT_DISABLE
//   MOT_STATUS           MOT_STATUS IDLE|MOVING|HOMING

#include <Arduino.h>
#include <string.h>

#include "command/dispatcher.h"
#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

namespace {

dispatcher::DoneResult motorMoveDone(void* ctx) {
  auto* m = static_cast<::components::LinearActuator*>(ctx);
  return m->moving() ? dispatcher::DoneResult::PENDING
                     : dispatcher::DoneResult::DONE;
}

dispatcher::DoneResult motorHomeDone(void* ctx) {
  auto* m = static_cast<::components::LinearActuator*>(ctx);
  if (m->moving()) return dispatcher::DoneResult::PENDING;
  if (m->homeFailed()) {
    m->clearHomeFailed();
    protocol::err("HOME_TIMEOUT");
    return dispatcher::DoneResult::FAILED;
  }
  return dispatcher::DoneResult::DONE;
}

}  // namespace

void hMotMove(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "MOT_MOVE <steps>");
    return;
  }
  long steps;
  if (!parseLong(cmd.argv[0], &steps)) {
    protocol::err("BAD_ARG", cmd.argv[0]);
    return;
  }
  protocol::ack("MOT_MOVE");
  components::motor.startMoveSteps(steps);
  dispatcher::registerPending("MOT_MOVE", &motorMoveDone, &components::motor);
}

void hMotRun(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "MOT_RUN <FWD|REV>");
    return;
  }
  bool forward;
  if (strcmp(cmd.argv[0], "FWD") == 0) {
    forward = true;
  } else if (strcmp(cmd.argv[0], "REV") == 0) {
    forward = false;
  } else {
    protocol::err("BAD_ARG", "expected FWD or REV");
    return;
  }
  components::motor.startContinuous(forward);
  protocol::ack("MOT_RUN");
}

void hMotStop(const ParsedCmd&) {
  components::motor.stop();
  protocol::ack("MOT_STOP");
}

void hMotHome(const ParsedCmd&) {
  protocol::ack("MOT_HOME");
  components::motor.startHome(components::limit);
  dispatcher::registerPending("MOT_HOME", &motorHomeDone, &components::motor);
}

void hMotPos(const ParsedCmd&) {
  Serial.print(F("MOT_POS "));
  Serial.println(components::motor.position());
}

void hMotEnable(const ParsedCmd&) {
  components::motor.enable();
  protocol::ack("MOT_ENABLE");
}

void hMotDisable(const ParsedCmd&) {
  components::motor.disable();
  protocol::ack("MOT_DISABLE");
}

void hMotStatus(const ParsedCmd&) {
  Serial.print(F("MOT_STATUS "));
  switch (components::motor.status()) {
    case ::components::LinearActuator::Status::IDLE:   Serial.println(F("IDLE")); break;
    case ::components::LinearActuator::Status::MOVING: Serial.println(F("MOVING")); break;
    case ::components::LinearActuator::Status::HOMING: Serial.println(F("HOMING")); break;
  }
}

}  // namespace handlers
}  // namespace biopayload
