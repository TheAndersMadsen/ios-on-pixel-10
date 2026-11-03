/* SPDX-License-Identifier: MIT
 * HOST ONLY. r2's kernel_oracle.c links blazer_bcm4390_join.c alone; r4's join also calls these two (blazer_bcm4390_ring.c,
 * blazer_bcm4390_scan.c). The reader oracle never runs a join, so they are never reached. */
#include "blazer_pcie1.h"
int b4_rx_witness(struct p1 *p, const char *when) { (void)p; (void)when; __builtin_trap(); }
int b4_rx_counters(struct p1 *p, const char *when) { (void)p; (void)when; __builtin_trap(); }
