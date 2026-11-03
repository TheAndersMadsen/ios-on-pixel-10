/* HOST: what each program gets from an overlay's hk_env text, by the hk-obs1 kernel's own code (hk_env_merge.h).
 * env_per_program RULES_FILE NAME... ; exit 1 if the text fails hk_env_check */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "hk_exec_rules.h"
#include "hk_env_merge.h"

static int
emit(void *ctx, const char *var, unsigned long len)
{
	(void)ctx;
	printf("    %.*s\n", (int)len, var);
	return 0;
}

int
main(int argc, char **argv)
{
	static char rules[HK_RULES_MAX + 2];
	FILE *f = argc > 1 ? fopen(argv[1], "rb") : NULL;
	size_t n;
	const char *why;

	if (f == NULL) {
		return 2;
	}
	n = fread(rules, 1, sizeof(rules) - 1, f);
	fclose(f);
	while (n && (rules[n - 1] == '\n' || rules[n - 1] == 0)) {
		n--;
	}
	rules[n] = 0;
	if (n + 1 > HK_RULES_MAX || (why = hk_env_check(rules)) != NULL) {
		printf("hk_env_check: %s\n", n + 1 > HK_RULES_MAX ? "over HK_RULES_MAX" : why);
		return 1;
	}
	printf("hk_env text %zu bytes (+NUL), hk_env_check OK\n", n);
	for (int i = 2; i < argc; i++) {
		char dyld[HK_VAR_MAX];
		int count, mirror, ndyld;
		unsigned lost;

		printf("%s:\n", argv[i]);
		hk_env_for_program(rules, argv[i], strlen(argv[i]), dyld, sizeof(dyld), emit, NULL, &count, &mirror, &ndyld, &lost);
		printf("  = %d variables, mirrored %s, DYLD rules %d, libraries lost %u\n", count, mirror ? "yes" : "no", ndyld, lost);
	}
	return 0;
}
