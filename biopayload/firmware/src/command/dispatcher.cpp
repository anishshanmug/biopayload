#include "command/dispatcher.h"

#include <Arduino.h>
#include <string.h>

#include "command/parser.h"
#include "command/protocol.h"
#include "state/state_machine.h"

namespace biopayload {
namespace dispatcher {
namespace {

constexpr size_t LINE_BUF_SIZE = 256;
constexpr size_t PENDING_MAX   = 4;

char     g_line[LINE_BUF_SIZE];
size_t   g_lineLen = 0;
bool     g_overflow = false;  // set when the current line overflowed; drop until next '\n'

struct PendingEntry {
  const char* tag;
  DoneCheck   check;
  void*       ctx;
};
PendingEntry g_pending[PENDING_MAX] = {};

const CommandEntry* findCommand(const char* name) {
  for (size_t i = 0; i < kCommandTableSize; ++i) {
    if (strcmp(kCommandTable[i].name, name) == 0) return &kCommandTable[i];
  }
  return nullptr;
}

void dispatchLine(char* line) {
  ParsedCmd cmd;
  if (!parseLine(line, cmd)) return;

  const CommandEntry* entry = findCommand(cmd.name);
  if (!entry) {
    protocol::err("UNKNOWN", cmd.name);
    return;
  }

  const uint8_t curMask = static_cast<uint8_t>(1u << static_cast<uint8_t>(stateMachine.current()));
  if ((entry->allowedStates & curMask) == 0) {
    protocol::err("BAD_STATE", cmd.name);
    return;
  }

  entry->handler(cmd);
}

void pollLine() {
  while (Serial.available()) {
    int b = Serial.read();
    if (b < 0) break;
    char c = static_cast<char>(b);
    if (c == '\r') continue;

    if (c == '\n') {
      if (g_overflow) {
        // We already emitted ERR LINE_TOO_LONG; just resync.
        g_overflow = false;
      } else {
        g_line[g_lineLen] = '\0';
        dispatchLine(g_line);
      }
      g_lineLen = 0;
      continue;
    }

    if (g_overflow) continue;

    if (g_lineLen + 1 >= LINE_BUF_SIZE) {
      protocol::err("LINE_TOO_LONG");
      g_overflow = true;
      g_lineLen = 0;
      continue;
    }

    g_line[g_lineLen++] = c;
  }
}

void pollPending() {
  for (size_t i = 0; i < PENDING_MAX; ++i) {
    if (g_pending[i].tag == nullptr || g_pending[i].check == nullptr) continue;
    DoneResult r = g_pending[i].check(g_pending[i].ctx);
    if (r == DoneResult::DONE) {
      protocol::done(g_pending[i].tag);
      g_pending[i] = PendingEntry{};
    } else if (r == DoneResult::FAILED) {
      // The check has already emitted ERR <code>. Just clear the slot.
      g_pending[i] = PendingEntry{};
    }
  }
}

}  // namespace

void poll() {
  pollLine();
  pollPending();
}

bool registerPending(const char* tag, DoneCheck isDone, void* ctx) {
  for (size_t i = 0; i < PENDING_MAX; ++i) {
    if (g_pending[i].tag == nullptr) {
      g_pending[i] = PendingEntry{ tag, isDone, ctx };
      return true;
    }
  }
  protocol::err("PENDING_FULL", tag);
  return false;
}

void clearPending() {
  for (size_t i = 0; i < PENDING_MAX; ++i) g_pending[i] = PendingEntry{};
}

}  // namespace dispatcher
}  // namespace biopayload
