/* Host run of hk_scwait (macOS): load the HK_SCWAIT_TEST dylib with HK_SCWAIT=1 and let it work for 6 s. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (argc > 2) unsetenv("HK_SCWAIT"); else setenv("HK_SCWAIT", "1", 1);
    if (!dlopen(argv[1], RTLD_NOW)) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    sleep(6);
    fprintf(stderr, "HOST done\n");
    return 0;
}
