// Central registry of all wire-protocol commands. Phase 2 adds all the
// component-specific handlers (PUMP_*, MOT_*, SPEC_*, LED_*, LIM_*) plus the
// SYS_STATUS roll-up. Experiment control commands (SET_CONFIG, START) come
// in Phase 3.
//
// State-mask convention:
//   MASK_ALL        - read-only / always-safe commands (status, ABORT, etc.)
//   MASK_IDLE_ONLY  - mutating commands that must not race with an experiment
//                     run; the experiment owns hardware while it's active.
//
// New commands: forward-declare the handler below, then add a row to
// kCommandTable. Keep the table sorted by family to make the COMMAND_REFERENCE
// diff easy to follow.

#include "command/dispatcher.h"
#include "state/state_machine.h"

namespace biopayload {

namespace handlers {

// System
void hPing      (const ParsedCmd&);
void hHello     (const ParsedCmd&);
void hState     (const ParsedCmd&);
void hAbort     (const ParsedCmd&);
void hSysStatus (const ParsedCmd&);

// Pump
void hPumpRun    (const ParsedCmd&);
void hPumpOn     (const ParsedCmd&);
void hPumpOff    (const ParsedCmd&);
void hPumpStatus (const ParsedCmd&);

// Motor
void hMotMove    (const ParsedCmd&);
void hMotRun     (const ParsedCmd&);
void hMotStop    (const ParsedCmd&);
void hMotHome    (const ParsedCmd&);
void hMotPos     (const ParsedCmd&);
void hMotEnable  (const ParsedCmd&);
void hMotDisable (const ParsedCmd&);
void hMotStatus  (const ParsedCmd&);

// LED
void hLedSet    (const ParsedCmd&);
void hLedOff    (const ParsedCmd&);
void hLedStatus (const ParsedCmd&);

// Limit switch
void hLimStatus (const ParsedCmd&);

// Spectral sensor
void hSpecRead   (const ParsedCmd&);
void hSpecGain   (const ParsedCmd&);
void hSpecAtime  (const ParsedCmd&);
void hSpecAstep  (const ParsedCmd&);
void hSpecStatus (const ParsedCmd&);

}  // namespace handlers

const CommandEntry kCommandTable[] = {
    // System (always-on)
    { "PING",       &handlers::hPing,      MASK_ALL },
    { "HELLO",      &handlers::hHello,     MASK_ALL },
    { "STATE",      &handlers::hState,     MASK_ALL },
    { "ABORT",      &handlers::hAbort,     MASK_ALL },
    { "SYS_STATUS", &handlers::hSysStatus, MASK_ALL },

    // Pump (writes are IDLE-only; experiment owns the pump while running)
    { "PUMP_RUN",    &handlers::hPumpRun,    MASK_IDLE_ONLY },
    { "PUMP_ON",     &handlers::hPumpOn,     MASK_IDLE_ONLY },
    { "PUMP_OFF",    &handlers::hPumpOff,    MASK_IDLE_ONLY },
    { "PUMP_STATUS", &handlers::hPumpStatus, MASK_ALL },

    // Motor (writes are IDLE-only)
    { "MOT_MOVE",    &handlers::hMotMove,    MASK_IDLE_ONLY },
    { "MOT_RUN",     &handlers::hMotRun,     MASK_IDLE_ONLY },
    { "MOT_STOP",    &handlers::hMotStop,    MASK_IDLE_ONLY },
    { "MOT_HOME",    &handlers::hMotHome,    MASK_IDLE_ONLY },
    { "MOT_POS",     &handlers::hMotPos,     MASK_ALL },
    { "MOT_ENABLE",  &handlers::hMotEnable,  MASK_IDLE_ONLY },
    { "MOT_DISABLE", &handlers::hMotDisable, MASK_IDLE_ONLY },
    { "MOT_STATUS",  &handlers::hMotStatus,  MASK_ALL },

    // LED (writes are IDLE-only)
    { "LED_SET",    &handlers::hLedSet,    MASK_IDLE_ONLY },
    { "LED_OFF",    &handlers::hLedOff,    MASK_IDLE_ONLY },
    { "LED_STATUS", &handlers::hLedStatus, MASK_ALL },

    // Limit switch (read-only)
    { "LIM_STATUS", &handlers::hLimStatus, MASK_ALL },

    // Spectral sensor (writes are IDLE-only; SPEC_READ may be useful as a
    // one-shot diagnostic at any point so it stays MASK_ALL)
    { "SPEC_READ",   &handlers::hSpecRead,   MASK_ALL },
    { "SPEC_GAIN",   &handlers::hSpecGain,   MASK_IDLE_ONLY },
    { "SPEC_ATIME",  &handlers::hSpecAtime,  MASK_IDLE_ONLY },
    { "SPEC_ASTEP",  &handlers::hSpecAstep,  MASK_IDLE_ONLY },
    { "SPEC_STATUS", &handlers::hSpecStatus, MASK_ALL },
};

const size_t kCommandTableSize = sizeof(kCommandTable) / sizeof(kCommandTable[0]);

}  // namespace biopayload
