/*
 * hackios: hk_inject_probe.dylib (MIT, original). Reusable hk_env load and sandbox-ABI probe.
 * The constructor is gated by HK_INJECT_PROBE=1, performs no interposition, starts no threads and keeps no state.
 * It writes directly to /dev/console so its receipt does not depend on stderr or os_log setup.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Private libsystem_sandbox API, already used by the stock iOS userland. Filter type 0 takes no extra argument. */
extern int sandbox_check(pid_t pid, const char *operation, int filter_type, ...);

#ifndef HK_CONSOLE_PATH
#define HK_CONSOLE_PATH "/dev/console"
#endif

__attribute__((constructor)) static void
hk_inject_probe(void)
{
	const char *gate = getenv("HK_INJECT_PROBE");
	if (gate == NULL || strcmp(gate, "1") != 0) {
		return;
	}
	pid_t pid = getpid();
	int self = sandbox_check(pid, NULL, 0);
	int operation = sandbox_check(pid, "mach-lookup", 0);
	int fd = open(HK_CONSOLE_PATH, O_WRONLY | O_NOCTTY | O_CLOEXEC);
	if (fd < 0) {
		return;
	}
	char line[320];
	int n = snprintf(line, sizeof(line), "HKINJECT: %s[%d] loaded self=%d operation=%d\n",
	    getprogname(), (int)pid, self, operation);
	if (n > 0) {
		(void)!write(fd, line, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1));
	}
	close(fd);
}
