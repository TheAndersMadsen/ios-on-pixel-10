/* SPDX-License-Identifier: MIT
 * HOST ONLY. The kernel's own reader, run on a composed overlay: the release tree's real varfs_overlay.h (hkov_check,
 * hkov_next, hkov_cover_check, hkov_same) and real blazer_bcm4390_join.c (b4_net_parse), linked with stubs for the radio
 * calls b4_net_parse never makes. The walk below is blazer_wifi_net.c blazer_wifi_net_secret's, minus the IODT lookup,
 * the pid-1 wait and the physical wipe. Prints lengths and flags only: never the name or the key.
 *
 *   kernel_oracle OVL MASK      exit 0: varfs would accept the blob with MASK, and the Wi-Fi reader finds a usable network
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include "blazer_pcie1.h"

#define WN_GROUP 26u                            /* blazer_wifi_net.c */
#define WN_PATH  "/private/var/hkcover/wifi/net"

/* Never called by b4_net_parse; present so the real translation unit links */
int p1_halt(struct p1 *p, uint32_t c, uint32_t d) { (void)p; (void)c; (void)d; abort(); }
int b4_ioctl(struct p1 *p, uint32_t c, uint8_t *b, uint16_t l) { (void)p; (void)c; (void)b; (void)l; abort(); }
int b4_poll(struct p1 *p) { (void)p; abort(); }
int b4_read_counters(struct p1 *p, unsigned w) { (void)p; (void)w; abort(); }
int b4_flow_create(struct p1 *p, const uint8_t *s, const uint8_t *d) { (void)p; (void)s; (void)d; abort(); }
int b4_tx_post(struct p1 *p, const uint8_t *f, uint32_t n) { (void)p; (void)f; (void)n; abort(); }
uint32_t b4_tx_free(const struct p1 *p) { (void)p; abort(); }
void b4_wipe_ioctl(struct p1 *p) { (void)p; abort(); }
int b4_console(struct p1 *p) { (void)p; abort(); }

static unsigned char *g_blob;

static int
run(int argc, char **argv)
{
	unsigned long total = 0, at = HKOV_HEADER_SIZE, size;
	unsigned long long hash = 0;
	unsigned int count = 0, covers = 0, mask, found = 0;
	const char *why;
	struct hkov_entry e;
	unsigned char *blob;
	FILE *f;

	if (argc != 3 || (f = fopen(argv[1], "rb")) == NULL) {
		fprintf(stderr, "usage: kernel_oracle OVL MASK\n");
		return 2;
	}
	mask = (unsigned int)strtoul(argv[2], NULL, 0);
	fseek(f, 0, SEEK_END);
	size = (unsigned long)ftell(f);
	fseek(f, 0, SEEK_SET);
	g_blob = blob = malloc(size ? size : 1);
	if (blob == NULL || fread(blob, 1, size, f) != size) {
		return 2;
	}
	fclose(f);
	why = hkov_check(blob, size, &total, &count, &hash);
	if (why != NULL) {
		printf("varfs: REJECT %s\n", why);
		return 1;
	}
	why = hkov_cover_check(blob, total, count, mask, &covers);
	if (why != NULL) {
		printf("varfs: REJECT covers: %s\n", why);
		return 1;
	}
	printf("varfs: ok, %u records, %lu bytes, groups 0x%08x, covers %u, group 26 applied %s\n", count, total,
	    hkov_groups(blob, total, count), covers, (mask & (1u << WN_GROUP)) ? "YES" : "no");
	for (unsigned int i = 0; i < count; i++) {
		if (hkov_next(blob, total, &at, &e, &why) != 1) {
			printf("wifi: walk stopped: %s\n", why);
			return 1;
		}
		if (e.group == WN_GROUP && e.type == 'f' && e.path_len == sizeof(WN_PATH) - 1 && hkov_same(e.path, WN_PATH, e.path_len)) {
			struct b4_network net;
			const char *bad = b4_net_parse(e.data, e.data_len, &net);

			found++;
			if (found > 1) {
				continue;       /* the kernel stops at the first; a second is a composer error */
			}
			if (bad != NULL) {
				printf("wifi: network unusable: %s\n", bad);
				return 1;
			}
			printf("wifi: network ok: ssid_len %u, open %d, have_mac %d, country %c%c/%c%c, rev %d, mode 0%o uid %u gid %u\n",
			    net.ssid_len, net.open, net.have_mac, net.abbrev[0], net.abbrev[1], net.ccode[0], net.ccode[1], net.rev,
			    e.mode, e.uid, e.gid);
			memset(&net, 0, sizeof(net));
		}
	}
	if (found != 1) {
		printf("wifi: %u network records (want 1)\n", found);
		return 1;
	}
	return (mask & (1u << WN_GROUP)) ? 1 : 0;
}

int
main(int argc, char **argv)
{
	int rc = run(argc, argv);

	free(g_blob);
	return rc;
}
