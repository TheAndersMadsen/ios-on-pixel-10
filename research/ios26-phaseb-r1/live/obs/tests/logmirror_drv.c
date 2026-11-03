/* HOST: the program the mirror is injected into. drv MODE N: lines | oslog | closefrom | flood */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <os/log.h>
#endif

int
main(int argc, char **argv)
{
	const char *mode = argc > 1 ? argv[1] : "lines";
	int n = argc > 2 ? atoi(argv[2]) : 10;

	if (strcmp(mode, "lines") == 0 || strcmp(mode, "flood") == 0) {
		for (int i = 0; i < n; i++) {
			fprintf(stderr, "MARKER %d\n", i);
		}
	} else if (strcmp(mode, "oslog") == 0) {
#if defined(__APPLE__)
		for (int i = 0; i < n; i++) {
			os_log(OS_LOG_DEFAULT, "OSLOG-MARKER %d", i);
		}
#else
		return 77;
#endif
	} else if (strcmp(mode, "closefrom") == 0) {
		for (int fd = 3; fd < 256; fd++) {
			close(fd);
		}
		usleep(100000);
		for (int i = 0; i < n; i++) {
			fprintf(stderr, "AFTER-CLOSE %d\n", i);
		}
		printf("survived\n");
	}
	fflush(stderr);
	usleep(400000);         /* let the reader drain before exit */
	return 0;
}
