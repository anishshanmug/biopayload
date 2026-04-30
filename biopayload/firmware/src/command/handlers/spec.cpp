// Spectral-sensor command handlers.
//
//   SPEC_READ              TELEM {f1:..., f2:..., f3:..., f4:..., f5:..., f6:...,
//                                  f7:..., f8:..., clear:..., nir:...}
//                          ERR  NO_SENSOR | READ_FAIL
//   SPEC_GAIN  <0..10>     ACK  SPEC_GAIN     (0=0.5x, 1=1x ... 10=512x)
//   SPEC_ATIME <0..255>    ACK  SPEC_ATIME
//   SPEC_ASTEP <0..65535>  ACK  SPEC_ASTEP
//   SPEC_STATUS            SPEC_STATUS READY|NOT_FOUND
//
// SPEC_READ is intentionally synchronous: the AS7341 read loop completes in a
// few hundred ms which we accept as a controlled hiccup of the dispatcher
// loop. Long-running spectral routines belong in scheduled actions (Phase 3),
// not in a 1st-order command.

#include <Arduino.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

namespace {

void emitReadingTelem(const ::components::SpectralReading& r) {
  protocol::telemBegin();
  Serial.print(F("\"f1\":"));    Serial.print(r.f1_415nm);
  Serial.print(F(",\"f2\":"));   Serial.print(r.f2_445nm);
  Serial.print(F(",\"f3\":"));   Serial.print(r.f3_480nm);
  Serial.print(F(",\"f4\":"));   Serial.print(r.f4_515nm);
  Serial.print(F(",\"f5\":"));   Serial.print(r.f5_555nm);
  Serial.print(F(",\"f6\":"));   Serial.print(r.f6_590nm);
  Serial.print(F(",\"f7\":"));   Serial.print(r.f7_630nm);
  Serial.print(F(",\"f8\":"));   Serial.print(r.f8_680nm);
  Serial.print(F(",\"clear\":")); Serial.print(r.clear);
  Serial.print(F(",\"nir\":"));  Serial.print(r.nir);
  protocol::telemEnd();
}

}  // namespace

void hSpecRead(const ParsedCmd&) {
  if (!components::spec.isReady()) {
    // Try a recovery probe in case the sensor was wired in after boot.
    if (!components::spec.tryReconnect()) {
      protocol::err("NO_SENSOR");
      return;
    }
  }
  ::components::SpectralReading r;
  if (!components::spec.read(r)) {
    protocol::err("READ_FAIL");
    return;
  }
  emitReadingTelem(r);
}

void hSpecGain(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "SPEC_GAIN <0..10>");
    return;
  }
  long g;
  if (!parseLong(cmd.argv[0], &g) || g < 0 || g > 10) {
    protocol::err("BAD_ARG", "gain out of range 0..10");
    return;
  }
  if (!components::spec.isReady()) {
    protocol::err("NO_SENSOR");
    return;
  }
  components::spec.setGain(static_cast<as7341_gain_t>(g));
  protocol::ack("SPEC_GAIN");
}

void hSpecAtime(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "SPEC_ATIME <0..255>");
    return;
  }
  long v;
  if (!parseLong(cmd.argv[0], &v) || v < 0 || v > 255) {
    protocol::err("BAD_ARG", "atime out of range 0..255");
    return;
  }
  if (!components::spec.isReady()) {
    protocol::err("NO_SENSOR");
    return;
  }
  components::spec.setATIME(static_cast<uint8_t>(v));
  protocol::ack("SPEC_ATIME");
}

void hSpecAstep(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "SPEC_ASTEP <0..65535>");
    return;
  }
  long v;
  if (!parseLong(cmd.argv[0], &v) || v < 0 || v > 65535) {
    protocol::err("BAD_ARG", "astep out of range 0..65535");
    return;
  }
  if (!components::spec.isReady()) {
    protocol::err("NO_SENSOR");
    return;
  }
  components::spec.setASTEP(static_cast<uint16_t>(v));
  protocol::ack("SPEC_ASTEP");
}

void hSpecStatus(const ParsedCmd&) {
  Serial.print(F("SPEC_STATUS "));
  Serial.println(components::spec.isReady() ? F("READY") : F("NOT_FOUND"));
}

}  // namespace handlers
}  // namespace biopayload
