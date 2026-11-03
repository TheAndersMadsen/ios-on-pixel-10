/*
 * hackios: hk_stderr_console.dylib (MIT, original). Point a daemon's stderr at /dev/console, so that with
 * OS_ACTIVITY_DT_MODE=YES its os_log lines reach the kernel log on a root we cannot edit (launchd's job sets stderr to
 * /dev/null; on a writable root StandardErrorPath=/dev/console does the same, see m1box/edit_logmirror_lsd_umd.py).
 * Injected with hk_env (DYLD_INSERT_LIBRARIES), gated by HK_STDERR_CONSOLE=1. Writes nothing else and keeps no state.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef HK_CONSOLE_PATH
#define HK_CONSOLE_PATH "/dev/console"
#endif

__attribute__((constructor)) static void
hk_stderr_console(void)
{
	const char *gate = getenv("HK_STDERR_CONSOLE");
	if (gate == NULL || strcmp(gate, "1") != 0) {
		return;
	}
	int fd = open(HK_CONSOLE_PATH, O_WRONLY | O_NOCTTY | O_CLOEXEC);
	if (fd < 0) {
		return;
	}
	if (fd != STDERR_FILENO) {
		if (dup2(fd, STDERR_FILENO) < 0) {
			close(fd);
			return;
		}
		close(fd);
	}
	char line[256];
	int n = snprintf(line, sizeof(line), "HKSTDERR: %s[%d] stderr -> " HK_CONSOLE_PATH "\n", getprogname(), (int)getpid());
	if (n > 0) {
		(void)!write(STDERR_FILENO, line, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1));
	}
}
