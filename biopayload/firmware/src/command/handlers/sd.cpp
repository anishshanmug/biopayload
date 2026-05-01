// SD card command handlers.
//
//   SD_STATUS           SD_STATUS READY total:<bytes> used:<bytes>
//                       SD_STATUS NOT_FOUND
//   SD_LIST [path]      SD_FILE <name> <bytes>  (one per entry, dirs show 0 bytes)
//                       SD_LIST_END
//   SD_DELETE <path>    ACK SD_DELETE | ERR SD_FAIL <path>
//
// SD_STATUS and SD_LIST are MASK_ALL (read-only, safe any time).
// SD_DELETE is MASK_IDLE_ONLY (destructive, only when not running an experiment).
//
// These commands are diagnostic / housekeeping -- the actual experiment data
// is written implicitly by sdLogger (state/sd_logger.{h,cpp}).

#include <Arduino.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "components/components.h"

namespace biopayload {
namespace handlers {

void hSdStatus(const ParsedCmd&) {
  if (!components::sd.present()) {
    // Try a quick re-probe in case card was inserted after boot.
    components::sd.tryReconnect();
  }
  if (!components::sd.present()) {
    Serial.println(F("SD_STATUS NOT_FOUND"));
    return;
  }
  Serial.print(F("SD_STATUS READY total:"));
  Serial.print(static_cast<unsigned long>(components::sd.totalBytes()));
  Serial.print(F(" used:"));
  Serial.println(static_cast<unsigned long>(components::sd.usedBytes()));
}

void hSdList(const ParsedCmd& cmd) {
  const char* path = (cmd.argc >= 1) ? cmd.argv[0] : "/";
  if (!components::sd.present()) {
    protocol::err("SD_FAIL", "no card");
    return;
  }
  bool ok = components::sd.listDir(path, [](const char* name, bool isDir, size_t size) {
    Serial.print(F("SD_FILE "));
    Serial.print(name);
    if (isDir) {
      Serial.println(F(" DIR"));
    } else {
      Serial.print(' ');
      Serial.println(size);
    }
  });
  if (!ok) {
    protocol::err("SD_FAIL", path);
    return;
  }
  Serial.println(F("SD_LIST_END"));
}

void hSdDelete(const ParsedCmd& cmd) {
  if (cmd.argc != 1) {
    protocol::err("BAD_ARG", "SD_DELETE <path>");
    return;
  }
  if (!components::sd.present()) {
    protocol::err("SD_FAIL", "no card");
    return;
  }
  if (!components::sd.remove(cmd.argv[0])) {
    protocol::err("SD_FAIL", cmd.argv[0]);
    return;
  }
  protocol::ack("SD_DELETE");
}

}  // namespace handlers
}  // namespace biopayload
