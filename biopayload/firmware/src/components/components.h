#ifndef BIOPAYLOAD_COMPONENTS_H
#define BIOPAYLOAD_COMPONENTS_H

// Component orchestrator: holds the firmware's singleton instances of every
// peripheral, plus the begin / tick / abort helpers that main() and the
// command handlers need.
//
// Adding a new component is a three-step edit:
//   1. add a header under src/components/ with begin()/tick()/abort() shape,
//   2. add a `extern Foo foo;` here and the singleton definition in
//      components.cpp,
//   3. extend beginAll() / tickAll() / abortAll() to include it.
//
// The boot banner emitted by beginAll() is the user-visible "is it wired?"
// indicator -- per-component status with `OK` / `NOT_FOUND` markers. The
// SYS_STATUS handler (in command/handlers/system.cpp) returns the same set.

#include "components/limit_switch.h"
#include "components/linear_actuator.h"
#include "components/peristaltic_pump.h"
#include "components/rgb_led.h"
#include "components/spectral_sensor.h"

namespace biopayload {
namespace components {

// Singleton instances. Pin assignments mirror the legacy demo / pin reference
// table in README.md; they live in components.cpp so a re-pin is a one-line
// edit and doesn't require a header rebuild.
extern ::components::PeristalticPump pump;
extern ::components::LinearActuator  motor;
extern ::components::RGBLed          led;
extern ::components::LimitSwitch     limit;
extern ::components::SpectralSensor  spec;

// Initialise every component. Prints a per-component status line so the
// operator sees presence detection at boot. Always returns true (a missing
// AS7341 is not a fatal error).
bool beginAll();

// Drive non-blocking state forward by one loop iteration.
void tickAll();

// Stop every component immediately. Used by the universal ABORT path.
void abortAll();

}  // namespace components
}  // namespace biopayload

#endif
