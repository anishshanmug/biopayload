#ifndef BIOPAYLOAD_COMMAND_PARSER_H
#define BIOPAYLOAD_COMMAND_PARSER_H

// In-place line tokenizer for serial commands.
//
// Usage: read a line into a writable char buffer (NUL-terminated, no trailing
// '\n'), pass it to parseLine(), and read out the resulting ParsedCmd.
//
// Conventions:
//   - The command name is uppercased in place.
//   - Tokenization stops as soon as the first non-whitespace, non-name char is
//     '{', '"' or '[' -- those signal a JSON / quoted argument that the
//     handler will read out of `rest`. Handlers like SET_CONFIG should grab
//     `cmd.rest` BEFORE inspecting argv.
//   - For "simple" commands like LED_SET 128 0 0, argc is set and argv[i]
//     points into the same buffer. Reading `rest` after tokenization yields
//     only the first token (subsequent NULs were written to split args).
//
// The parser does NOT allocate. It mutates the input buffer.

#include <stdint.h>

namespace biopayload {

constexpr uint8_t MAX_ARGS = 8;

struct ParsedCmd {
  const char* name;            // uppercased, NUL-terminated; never null
  uint8_t     argc;            // number of populated argv slots
  const char* argv[MAX_ARGS];  // each NUL-terminated; valid for [0..argc)
  const char* rest;            // remainder of line after the name; "" if none
};

// Returns true on a non-empty command. Comments (lines starting with '#') and
// blank/whitespace-only lines return false and produce no error output.
bool parseLine(char* buf, ParsedCmd& out);

// Helper: parse argv[i] as a signed long. Returns true on success and writes
// to *out. False if the string is empty or contains non-numeric trailing
// characters.
bool parseLong(const char* s, long* out);

}  // namespace biopayload

#endif
