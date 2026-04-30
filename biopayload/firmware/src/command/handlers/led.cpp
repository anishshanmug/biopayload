// RGB LED command handlers.
//
//   LED_SET <r> <g> <b>   ACK LED_SET     (each channel 0-255; ERR BAD_ARG otherwise)
//   LED_OFF               ACK LED_OFF
//   LED_STATUS            LED_STATUS <r> <g> <b>     (last commanded color)

#include <Arduino.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

namespace {

bool parseChannel(const char* s, uint8_t* out) {
  long v;
  if (!parseLong(s, &v)) return false;
  if (v < 0 || v > 255) return false;
  *out = static_cast<uint8_t>(v);
  return true;
}

}  // namespace

void hLedSet(const ParsedCmd& cmd) {
  if (cmd.argc != 3) {
    protocol::err("BAD_ARG", "LED_SET <r> <g> <b>");
    return;
  }
  uint8_t r, g, b;
  if (!parseChannel(cmd.argv[0], &r) ||
      !parseChannel(cmd.argv[1], &g) ||
      !parseChannel(cmd.argv[2], &b)) {
    protocol::err("BAD_ARG", "channel out of range 0..255");
    return;
  }
  components::led.set(r, g, b);
  protocol::ack("LED_SET");
}

void hLedOff(const ParsedCmd&) {
  components::led.off();
  protocol::ack("LED_OFF");
}

void hLedStatus(const ParsedCmd&) {
  Serial.print(F("LED_STATUS "));
  Serial.print(components::led.r());
  Serial.print(' ');
  Serial.print(components::led.g());
  Serial.print(' ');
  Serial.println(components::led.b());
}

}  // namespace handlers
}  // namespace biopayload
