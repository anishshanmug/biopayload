#ifndef BIOPAYLOAD_COMMAND_DISPATCHER_H
#define BIOPAYLOAD_COMMAND_DISPATCHER_H

// Command dispatcher: reads newline-delimited lines from `Serial`, runs them
// through the parser, looks them up in the command table, gates them on the
// current state, and routes to a handler.
//
// Long-running commands kick off non-blocking work and register a "pending
// DONE" entry. The dispatcher polls these every loop iteration and emits
// `DONE <tag>` once the bound check returns true. ABORT clears all pending
// entries silently (the host already knows from `ACK ABORT`).

#include <stddef.h>
#include <stdint.h>

namespace biopayload {

struct ParsedCmd;

using Handler = void (*)(const ParsedCmd&);

struct CommandEntry {
  const char* name;
  Handler     handler;
  uint8_t     allowedStates;  // bitmask of stateMask(State::X)
};

namespace dispatcher {

// Drain Serial, dispatch any complete lines, and poll pending DONEs. Call
// once per loop().
void poll();

// Pending-DONE registration. The bound check is a function pointer with an
// opaque ctx pointer (component-scoped state lives in the caller, not here).
// `tag` must outlive the registration -- pass a string literal or a static.
//
// The check returns three states:
//   PENDING  - operation still running; poll again later
//   DONE     - succeeded; dispatcher emits "DONE <tag>" and clears the slot
//   FAILED   - operation failed; the check is responsible for having already
//              emitted the appropriate "ERR <code>" line. The dispatcher just
//              clears the slot, no DONE.
enum class DoneResult : uint8_t {
  PENDING = 0,
  DONE    = 1,
  FAILED  = 2,
};
using DoneCheck = DoneResult (*)(void* ctx);
bool registerPending(const char* tag, DoneCheck isDone, void* ctx = nullptr);

// Wipe every pending DONE entry without emitting anything. Called by ABORT.
void clearPending();

}  // namespace dispatcher

// Provided by command/command_table.cpp.
extern const CommandEntry kCommandTable[];
extern const size_t       kCommandTableSize;

}  // namespace biopayload

#endif
