// Central registry of all wire-protocol commands. Phase 1 only registers the
// always-on system commands; component-specific handlers (PUMP_*, MOT_*,
// SPEC_*, LED_*, LIM_*) and the experiment control commands (SET_CONFIG,
// START) are added in later phases.
//
// New commands: forward-declare the handler below, then add a row to
// kCommandTable. Keep the table sorted by family to make the COMMAND_REFERENCE
// diff easy to follow.

#include "command/dispatcher.h"
#include "state/state_machine.h"

namespace biopayload {

namespace handlers {
void hPing (const ParsedCmd&);
void hHello(const ParsedCmd&);
void hState(const ParsedCmd&);
void hAbort(const ParsedCmd&);
}

const CommandEntry kCommandTable[] = {
    // System (always-on)
    { "PING",  &handlers::hPing,  MASK_ALL },
    { "HELLO", &handlers::hHello, MASK_ALL },
    { "STATE", &handlers::hState, MASK_ALL },
    { "ABORT", &handlers::hAbort, MASK_ALL },
};

const size_t kCommandTableSize = sizeof(kCommandTable) / sizeof(kCommandTable[0]);

}  // namespace biopayload
