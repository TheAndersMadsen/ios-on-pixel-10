/* SPDX-License-Identifier: MIT
 * Runs the actual XNU overlay and exec-rule consumers against the candidate.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>

int main(int argc, char **argv)
{
	assert(argc == 2);
	FILE *file = fopen(argv[1], "rb"); assert(file);
	assert(!fseek(file, 0, SEEK_END)); long size = ftell(file); rewind(file);
	assert(size > 24 && size < (48 << 20));
	unsigned char *data = malloc((size_t)size); assert(data);
	assert(fread(data, 1, (size_t)size, file) == (size_t)size); fclose(file);
	unsigned long total, offset = 24;
	unsigned int count, cover;
	unsigned long long hash;
	const unsigned int mask = 0x20080081u;
	assert(!hkov_check(data, (unsigned long)size, &total, &count, &hash));
	assert(!hkov_cover_check(data, total, count, mask, &cover) && cover == 1);
	char env[HK_RULES_MAX] = {0}, deny[HK_RULES_MAX] = {0};
	const char *why = NULL;
	unsigned int env_records = 0, files = 0;
	for (unsigned int i = 0; i < count; i++) {
		struct hkov_entry entry;
		assert(hkov_next(data, total, &offset, &entry, &why) == 1);
		if (!(mask & (1u << entry.group))) continue;
		if (entry.type == 'c' && !strcmp(entry.path, "hk_env")) {
			assert(!hk_rules_append(env, sizeof(env), (const char *)entry.data, entry.data_len));
			env_records++;
		}
		if (entry.type == 'c' && !strcmp(entry.path, "hk_deny"))
			assert(!hk_rules_append(deny, sizeof(deny), (const char *)entry.data, entry.data_len));
		if (entry.type == 'f' && !strcmp(entry.path, "/private/var/hk/hkbtkeychain.dylib")) {
			assert(entry.mode == 0755 && entry.uid == 0 && entry.gid == 0);
			files++;
		}
	}
	assert(files == 1 && env_records == 1 && !hk_env_check(env));
	assert(!hk_list_has(deny, "bluetoothd", 10));
	const char *cursor = env, *variable;
	unsigned long length;
	int in_rule = 0;
	const char *expected[] = {"BT_HCI_TRANSPORT=H4:POSIX", "BT_CHIP=ACI~BT", "HK_BT_KEYCHAIN_TRACE=1",
	    "DYLD_INSERT_LIBRARIES=/private/var/hk/hkbtkeychain.dylib"};
	unsigned int seen[4] = {0};
	while (hk_env_next(&cursor, &in_rule, "bluetoothd", 10, &variable, &length)) {
		unsigned int matches = 0;
		for (unsigned int i = 0; i < 4; i++) if (length == strlen(expected[i]) && !memcmp(variable, expected[i], length)) {
			seen[i]++; matches++;
		}
		assert(matches == 1);
	}
	for (unsigned int i = 0; i < 4; i++) assert(seen[i] == 1);
	cursor = env; in_rule = 0; unsigned int preserved = 0;
	const char *track = "DYLD_INSERT_LIBRARIES=/private/var/hk/hgltrack.dylib";
	while (hk_env_next(&cursor, &in_rule, "backboardd", 10, &variable, &length)) {
		if (length == strlen(track) && !memcmp(variable, track, length)) preserved++;
	}
	assert(preserved == 1);
	free(data);
	puts("PASS actual XNU overlay/exec consumer: one BT observer, exact env, enabled job, retained hgltrack");
	return 0;
}
