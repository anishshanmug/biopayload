#include "command/parser.h"

#include <ctype.h>
#include <stdlib.h>

namespace biopayload {

bool parseLine(char* buf, ParsedCmd& out) {
  out.name = "";
  out.argc = 0;
  out.rest = "";
  if (!buf) return false;

  char* p = buf;
  while (*p && isspace(static_cast<unsigned char>(*p))) ++p;
  if (*p == '\0' || *p == '#') return false;

  out.name = p;
  while (*p && !isspace(static_cast<unsigned char>(*p))) {
    *p = static_cast<char>(toupper(static_cast<unsigned char>(*p)));
    ++p;
  }
  if (*p) {
    *p++ = '\0';
    while (*p && isspace(static_cast<unsigned char>(*p))) ++p;
  }

  // `rest` captures everything after the name verbatim. Handlers that take
  // JSON / quoted args MUST read `rest` before they look at argv, because the
  // tokenizer below writes NULs into the same buffer.
  out.rest = p;

  while (*p && out.argc < MAX_ARGS) {
    if (*p == '{' || *p == '"' || *p == '[') break;  // JSON / quoted: leave for `rest`.

    out.argv[out.argc++] = p;
    while (*p && !isspace(static_cast<unsigned char>(*p))) ++p;
    if (*p) {
      *p++ = '\0';
      while (*p && isspace(static_cast<unsigned char>(*p))) ++p;
    }
  }

  return true;
}

bool parseLong(const char* s, long* out) {
  if (!s || !*s || !out) return false;
  char* end = nullptr;
  long v = strtol(s, &end, 10);
  if (end == s || (end && *end != '\0')) return false;
  *out = v;
  return true;
}

}  // namespace biopayload
