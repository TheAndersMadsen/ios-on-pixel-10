/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors
 * Status-only observation; every Security API call is forwarded unchanged.
 */
#if defined(HKBTKC_ENABLED) && HKBTKC_ENABLED
#ifdef HKBTKC_HOST_TEST
#include "test_shim.h"
#else
#include <CoreFoundation/CoreFoundation.h>
#include <Security/SecItem.h>
#include <errno.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#endif

#define HKBTKC_LIMIT 64u
static unsigned int hkbtkc_active, hkbtkc_records, hkbtkc_lost;
static int hkbtkc_fd = -1;

static void
hkbtkc_emit(const char *format, ...)
{
	char line[256];
	va_list args;
	va_start(args, format);
	int n = vsnprintf(line, sizeof(line), format, args);
	va_end(args);
	if (n <= 0 || (size_t)n >= sizeof(line)) {
		__atomic_add_fetch(&hkbtkc_lost, 1, __ATOMIC_RELAXED);
		return;
	}
	size_t offset = 0;
	for (unsigned int attempt = 0; offset < (size_t)n && attempt < 4; attempt++) {
		ssize_t wrote = write(hkbtkc_fd, line + offset, (size_t)n - offset);
		if (wrote > 0 && (size_t)wrote <= (size_t)n - offset) offset += (size_t)wrote;
		else if (wrote < 0 && errno == EINTR) continue;
		else break;
	}
	if (offset != (size_t)n) __atomic_add_fetch(&hkbtkc_lost, 1, __ATOMIC_RELAXED);
}

static unsigned int
hkbtkc_begin(const char *operation, uintptr_t caller)
{
	int saved_errno = errno;
	unsigned int id = 0;
	if (__atomic_load_n(&hkbtkc_active, __ATOMIC_ACQUIRE)) {
		unsigned int old = __atomic_load_n(&hkbtkc_records, __ATOMIC_RELAXED);
		while (old < HKBTKC_LIMIT) {
			if (__atomic_compare_exchange_n(&hkbtkc_records, &old, old + 1u,
			    0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {
				id = old + 1u;
				break;
			}
		}
	}
	if (id) hkbtkc_emit("HKBTKC: pid %d id %u %s enter caller 0x%llx lost %u\n",
	    getpid(), id, operation, (unsigned long long)caller, __atomic_load_n(&hkbtkc_lost, __ATOMIC_RELAXED));
	errno = saved_errno;
	return id;
}

static void
hkbtkc_end(unsigned int id, const char *operation, OSStatus status)
{
	int saved_errno = errno;
	if (id) hkbtkc_emit("HKBTKC: pid %d id %u %s return status %d errno %d lost %u\n",
	    getpid(), id, operation, (int)status, saved_errno, __atomic_load_n(&hkbtkc_lost, __ATOMIC_RELAXED));
	errno = saved_errno;
}

OSStatus hk_bt_SecItemCopyMatching(CFDictionaryRef, CFTypeRef *);
OSStatus hk_bt_SecItemAdd(CFDictionaryRef, CFTypeRef *);
OSStatus hk_bt_SecItemUpdate(CFDictionaryRef, CFDictionaryRef);
OSStatus hk_bt_SecItemDelete(CFDictionaryRef);

OSStatus
hk_bt_SecItemCopyMatching(CFDictionaryRef query, CFTypeRef *result)
{
	unsigned int id = hkbtkc_begin("copy", (uintptr_t)__builtin_return_address(0));
	OSStatus status = SecItemCopyMatching(query, result);
	hkbtkc_end(id, "copy", status);
	return status;
}

OSStatus
hk_bt_SecItemAdd(CFDictionaryRef attrs, CFTypeRef *result)
{
	unsigned int id = hkbtkc_begin("add", (uintptr_t)__builtin_return_address(0));
	OSStatus status = SecItemAdd(attrs, result);
	hkbtkc_end(id, "add", status);
	return status;
}

OSStatus
hk_bt_SecItemUpdate(CFDictionaryRef query, CFDictionaryRef attrs)
{
	unsigned int id = hkbtkc_begin("update", (uintptr_t)__builtin_return_address(0));
	OSStatus status = SecItemUpdate(query, attrs);
	hkbtkc_end(id, "update", status);
	return status;
}

OSStatus
hk_bt_SecItemDelete(CFDictionaryRef query)
{
	unsigned int id = hkbtkc_begin("delete", (uintptr_t)__builtin_return_address(0));
	OSStatus status = SecItemDelete(query);
	hkbtkc_end(id, "delete", status);
	return status;
}

#ifndef HKBTKC_HOST_TEST
/* dyld applies replacement to other images; these original calls stay bound
 * to Security. Loader/interposition acceptance still needs an actual guest.
 */
#define HKBTKC_INTERPOSE(replacement, original) \
	__attribute__((used, section("__DATA,__interpose,interposing"))) \
	static const struct { const void *new_fn, *old_fn; } hkbtkc_##original = \
	{(const void *)&replacement, (const void *)&original}
HKBTKC_INTERPOSE(hk_bt_SecItemCopyMatching, SecItemCopyMatching);
HKBTKC_INTERPOSE(hk_bt_SecItemAdd, SecItemAdd);
HKBTKC_INTERPOSE(hk_bt_SecItemUpdate, SecItemUpdate);
HKBTKC_INTERPOSE(hk_bt_SecItemDelete, SecItemDelete);
__attribute__((constructor))
#endif
static void
hkbtkc_init(void)
{
	int saved_errno = errno;
	const char *who = getprogname();
	const char *enabled = getenv("HK_BT_KEYCHAIN_TRACE");
	if (!who || strcmp(who, "bluetoothd") != 0 || !enabled || strcmp(enabled, "1") != 0) {
		errno = saved_errno;
		return;
	}
	hkbtkc_fd = open("/dev/console", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
	int console_errno = hkbtkc_fd < 0 ? errno : 0;
	if (hkbtkc_fd < 0) hkbtkc_fd = STDERR_FILENO;
	hkbtkc_emit("HKBTKC: v1 start pid %d main 0x%llx slide 0x%llx console_errno %d\n",
	    getpid(), (unsigned long long)(uintptr_t)_dyld_get_image_header(0),
	    (unsigned long long)_dyld_get_image_vmaddr_slide(0), console_errno);
	__atomic_store_n(&hkbtkc_active, 1, __ATOMIC_RELEASE);
	errno = saved_errno;
}
#endif
