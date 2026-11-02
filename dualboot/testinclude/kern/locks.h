/* SPDX-License-Identifier: MIT
 * Single-thread host model only. Does not establish XNU locking correctness.
 */
#ifndef HK_TEST_LOCKS_H
#define HK_TEST_LOCKS_H
#include <assert.h>
#define LCK_GRP_DECLARE(n, label) int n __attribute__((unused))
#define LCK_MTX_DECLARE(n, group) int n
static inline void lck_mtx_lock(int *p) { assert(*p == 0); *p = 1; }
static inline void lck_mtx_unlock(int *p) { assert(*p == 1); *p = 0; }
#endif
