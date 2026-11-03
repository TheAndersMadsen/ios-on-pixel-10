/*
 * hackios hk-obs1: hk_logmirror.dylib (MIT, original). The log mirror for any daemon hk_env names, replacing
 * hk_stderr_console.dylib (app2) which pointed one daemon's stderr straight at /dev/console.
 *
 * Injected by one hk_env rule (DYLD_INSERT_LIBRARIES, merged by the kernel with the program's own libraries), with
 * OS_ACTIVITY_DT_MODE=YES so libsystem_trace also writes each os_log line to stderr, and gated by HK_LOGMIRROR:
 *   HK_LOGMIRROR=1        on, 8 lines/s per program, burst 64 (hk_logmirror_fmt.h)
 *   HK_LOGMIRROR=R[,B]    R lines/s (0: no per-program limit), burst B
 *
 * The constructor puts one end of a socket pair on fd 2 and a thread reads the other end. The daemon is never held up:
 * its end is non-blocking (a full buffer drops the line, never waits) and SO_NOSIGPIPE (if the daemon closes the
 * reader's fd, a write fails with EPIPE instead of killing it). The thread cuts each line to 320 bytes, drops the date
 * and the "prog[pid:tid]" head, writes "HKL <prog>[<pid>] <message>" to /dev/console in one write, and counts what its
 * per-program budget refused ("HKL <prog>[<pid>] -- N lines dropped" when it can say so). The kernel (hk_obs) keeps a
 * second, global budget for all "HKL " lines and counts per program. If anything fails at the start, stderr stays as
 * it was and the program runs as without the library.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "hk_logmirror_fmt.h"

#ifndef HK_CONSOLE_PATH
#define HK_CONSOLE_PATH "/dev/console"
#endif

#if defined(__APPLE__)
#define HKM_PROG() getprogname()
#else
extern char *program_invocation_short_name;
#define HKM_PROG() program_invocation_short_name
#endif

struct hkm {
	int rd, con, pid;
	const char *prog;
	struct hkm_bucket bucket;
	uint64_t dropped, said_drop_us;
};

static struct hkm hkm;

static uint64_t
hkm_now_us(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

static void
hkm_write(struct hkm *m, const char *s, size_t n)
{
	ssize_t w;

	do {
		w = write(m->con, s, n);
	} while (w < 0 && errno == EINTR);
	if (w < 0 && errno == EBADF) {
		/* The daemon closed our console fd (closefrom). Open it again, at most once a second */
		uint64_t now = hkm_now_us();

		if (now - m->said_drop_us > 1000000u) {
			m->said_drop_us = now;
			m->con = open(HK_CONSOLE_PATH, O_WRONLY | O_NOCTTY | O_CLOEXEC);
		}
	}
}

static void
hkm_line(struct hkm *m, const char *s, size_t n, int cut)
{
	char out[HKM_LINE_MAX];
	size_t at = hkm_message_at(s, n, m->prog), len;
	uint64_t now = hkm_now_us();

	if (!hkm_take(&m->bucket, now)) {
		m->dropped++;
		return;
	}
	if (m->dropped != 0) {
		char note[96];
		int k = snprintf(note, sizeof(note), "HKL %.32s[%d] -- %llu lines dropped (HK_LOGMIRROR budget)\n", m->prog, m->pid,
		    (unsigned long long)m->dropped);

		if (k > 0 && (size_t)k < sizeof(note)) {
			hkm_write(m, note, (size_t)k);
		}
		m->dropped = 0;
	}
	len = hkm_format(out, m->prog, m->pid, s + at, n - at, cut);
	hkm_write(m, out, len);
}

static void *
hkm_reader(void *arg)
{
	struct hkm *m = arg;
	char buf[4096], line[HKM_LINE_MAX];
	size_t have = 0;
	int cut = 0;

	for (;;) {
		ssize_t r = read(m->rd, buf, sizeof(buf));

		if (r < 0 && errno == EINTR) {
			continue;
		}
		if (r <= 0) {
			break;  /* every writer gone, or our fd closed by the daemon */
		}
		for (ssize_t i = 0; i < r; i++) {
			char c = buf[i];

			if (c == '\n') {
				if (have != 0 || cut) {
					hkm_line(m, line, have, cut);
				}
				have = 0;
				cut = 0;
			} else if (have < sizeof(line)) {
				line[have++] = c;
			} else {
				cut = 1;
			}
		}
	}
	if (have != 0) {
		hkm_line(m, line, have, cut);
	}
	return NULL;
}

__attribute__((constructor)) static void
hk_logmirror(void)
{
	struct hkm *m = &hkm;
	int sv[2], saved, one = 1, size = 65536, fl;
	pthread_attr_t attr;
	pthread_t thread;
	char banner[160];
	int k;

	if (!hkm_parse(getenv("HK_LOGMIRROR"), &m->bucket.rate, &m->bucket.burst)) {
		return;
	}
	m->prog = HKM_PROG();
	if (m->prog == NULL) {
		m->prog = "?";
	}
	m->pid = (int)getpid();
	m->con = open(HK_CONSOLE_PATH, O_WRONLY | O_NOCTTY | O_CLOEXEC);
	if (m->con < 0) {
		return;
	}
	if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) {
		close(m->con);
		return;
	}
	(void)fcntl(sv[0], F_SETFD, FD_CLOEXEC);
	(void)setsockopt(sv[1], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size));
	(void)setsockopt(sv[0], SOL_SOCKET, SO_RCVBUF, &size, sizeof(size));
#ifdef SO_NOSIGPIPE
	(void)setsockopt(sv[1], SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
#else
	(void)one;      /* Linux host test only: no SO_NOSIGPIPE there */
#endif
	fl = fcntl(sv[1], F_GETFL);
	if (fl < 0 || fcntl(sv[1], F_SETFL, fl | O_NONBLOCK) != 0) {
		goto undo_pair;
	}
	saved = dup(STDERR_FILENO);
	if (dup2(sv[1], STDERR_FILENO) < 0) {
		if (saved >= 0) {
			close(saved);
		}
		goto undo_pair;
	}
	close(sv[1]);
	m->rd = sv[0];
	if (pthread_attr_init(&attr) != 0 || pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED) != 0 ||
	    pthread_create(&thread, &attr, hkm_reader, m) != 0) {
		/* No thread: put stderr back as it was */
		if (saved >= 0) {
			(void)dup2(saved, STDERR_FILENO);
			close(saved);
		}
		close(sv[0]);
		close(m->con);
		return;
	}
	pthread_attr_destroy(&attr);
	if (saved >= 0) {
		close(saved);
	}
	k = snprintf(banner, sizeof(banner), "HKL %.32s[%d] -- mirror on: os_log and stderr, %u lines/s burst %u, %u B a line\n",
	    m->prog, m->pid, m->bucket.rate, m->bucket.burst, HKM_LINE_MAX);
	if (k > 0 && (size_t)k < sizeof(banner)) {
		hkm_write(m, banner, (size_t)k);
	}
	return;
undo_pair:
	close(sv[0]);
	close(sv[1]);
	close(m->con);
}
