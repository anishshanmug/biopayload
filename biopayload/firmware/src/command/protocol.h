#ifndef BIOPAYLOAD_COMMAND_PROTOCOL_H
#define BIOPAYLOAD_COMMAND_PROTOCOL_H

// Wire-protocol output helpers. Every line emitted to the host goes through
// this header so we keep formatting consistent with COMMAND_REFERENCE.md.
//
//   ACK <cmd>           - synchronous acknowledgement (the dispatcher accepted
//                         and dispatched the command; for instant commands
//                         this is also the "done" signal)
//   ACK <cmd> <arg>     - acknowledgement that carries a single payload arg
//                         (used by HELLO to return the firmware version)
//   DONE <cmd>          - asynchronous completion signal for long-running
//                         commands; emitted by the dispatcher's pending-DONE
//                         tracker, not by handlers directly
//   ERR <code> [msg]    - command rejected or aborted (UNKNOWN, BAD_STATE,
//                         BAD_ARG, NO_SENSOR, ...)
//   STATE <name>        - state machine transition announcement
//   TELEM { ... }       - JSON-ish telemetry record (callers append their own
//                         "k":v pairs between telemBegin() and telemEnd())

#include <Arduino.h>

namespace biopayload {
namespace protocol {

inline void ack(const char* cmd) {
  Serial.print(F("ACK "));
  Serial.println(cmd);
}

inline void ackArg(const char* cmd, const char* arg) {
  Serial.print(F("ACK "));
  Serial.print(cmd);
  Serial.print(' ');
  Serial.println(arg);
}

inline void done(const char* cmd) {
  Serial.print(F("DONE "));
  Serial.println(cmd);
}

inline void err(const char* code, const char* msg = nullptr) {
  Serial.print(F("ERR "));
  Serial.print(code);
  if (msg && *msg) {
    Serial.print(' ');
    Serial.print(msg);
  }
  Serial.println();
}

inline void state(const char* name) {
  Serial.print(F("STATE "));
  Serial.println(name);
}

inline void telemBegin() { Serial.print(F("TELEM {")); }
inline void telemEnd()   { Serial.println('}'); }

}  // namespace protocol
}  // namespace biopayload

#endif
