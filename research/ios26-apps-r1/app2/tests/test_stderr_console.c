/* Host test driver: writes one marker to stderr. Run with the test dylib inserted (see build_stderr_console.sh). */
#include <stdio.h>
int main(void) { fprintf(stderr, "MARKER-STDERR\n"); return 0; }
