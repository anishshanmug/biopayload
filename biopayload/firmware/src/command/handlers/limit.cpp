// Limit-switch command handlers.
//
//   LIM_STATUS    LIM_STATUS OPEN|CLOSED

#include <Arduino.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

void hLimStatus(const ParsedCmd&) {
  Serial.print(F("LIM_STATUS "));
  Serial.println(components::limit.closed() ? F("CLOSED") : F("OPEN"));
}

}  // namespace handlers
}  // namespace biopayload
