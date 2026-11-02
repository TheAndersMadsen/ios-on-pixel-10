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

struct hkbtkc_main {
	uintptr_t header;
	intptr_t slide;
	unsigned int known, index;
	char uuid[33];
};

static uint32_t
hkbtkc_u32(const unsigned char *p)
{
	uint32_t value;
	memcpy(&value, p, sizeof(value));
	return value;
}

static uint64_t
hkbtkc_u64(const unsigned char *p)
{
	uint64_t value;
	memcpy(&value, p, sizeof(value));
	return value;
}

/* dyld inserts opt-in dylibs before the executable. Index zero is therefore
 * not a main-image contract. Inspect the loaded ARM64 MH_EXECUTE header and
 * require its UUID and file-backed __TEXT address to agree with dyld's slide.
 * Mach-O field offsets below are wire-format facts, not copied loader code.
 */
static int
hkbtkc_main_image(const unsigned char *p, intptr_t slide, struct hkbtkc_main *out)
{
	if (!p || hkbtkc_u32(p) != 0xfeedfacfu ||
	    hkbtkc_u32(p + 4) != 0x0100000cu || hkbtkc_u32(p + 12) != 2u) return 0;
	uint32_t commands = hkbtkc_u32(p + 16), bytes = hkbtkc_u32(p + 20);
	if (!commands || commands > 4096u || bytes > 131072u || commands > bytes / 8u) return 0;
	uint32_t at = 32, end = 32 + bytes;
	unsigned int uuid_seen = 0, text_seen = 0;
	uint64_t preferred = 0;
	unsigned char uuid[16] = {0};
	for (uint32_t n = 0; n < commands; n++) {
		if (end - at < 8) return 0;
		uint32_t cmd = hkbtkc_u32(p + at), size = hkbtkc_u32(p + at + 4);
		if (size < 8 || (size & 7u) || size > end - at) return 0;
		if (cmd == 0x1bu) {
			if (size != 24 || uuid_seen++) return 0;
			memcpy(uuid, p + at + 8, sizeof(uuid));
		} else if (cmd == 0x19u) {
			if (size < 72) return 0;
			uint32_t sections = hkbtkc_u32(p + at + 64);
			if (sections > (size - 72) / 80u) return 0;
			static const char text_name[16] = "__TEXT";
			if (!memcmp(p + at + 8, text_name, sizeof(text_name))) {
				if (text_seen++ || hkbtkc_u64(p + at + 40) != 0 ||
				    hkbtkc_u64(p + at + 48) < end ||
				    hkbtkc_u64(p + at + 32) < hkbtkc_u64(p + at + 48)) return 0;
				preferred = hkbtkc_u64(p + at + 24);
			}
		}
		at += size;
	}
	if (at != end || uuid_seen != 1 || text_seen != 1) return 0;
	uintptr_t header = (uintptr_t)p;
	/* Do not form an overflowing preferred+slide or negate INTPTR_MIN. */
	if (slide >= 0) {
		if (preferred > UINTPTR_MAX - (uintptr_t)slide || preferred + (uintptr_t)slide != header) return 0;
	} else {
		uintptr_t magnitude = (uintptr_t)(-(slide + 1)) + 1u;
		if (preferred < magnitude || preferred - magnitude != header) return 0;
	}
	static const char hex[] = "0123456789abcdef";
	unsigned int nonzero = 0;
	for (unsigned int i = 0; i < sizeof(uuid); i++) {
		nonzero |= uuid[i];
		out->uuid[2 * i] = hex[uuid[i] >> 4];
		out->uuid[2 * i + 1] = hex[uuid[i] & 15u];
	}
	if (!nonzero) return 0;
	out->uuid[32] = 0;
	out->header = header;
	out->slide = slide;
	out->known = 1;
	return 1;
}

static struct hkbtkc_main
hkbtkc_find_main(void)
{
	struct hkbtkc_main result = {0};
	unsigned int count = _dyld_image_count();
	if (count > 4096u) return result;
	for (unsigned int i = 0; i < count; i++) {
		const unsigned char *header = (const unsigned char *)_dyld_get_image_header(i);
		if (!header || hkbtkc_u32(header + 12) != 2u) continue;
		intptr_t slide = _dyld_get_image_vmaddr_slide(i);
		if ((const void *)header != (const void *)_dyld_get_image_header(i)) return (struct hkbtkc_main){0};
		struct hkbtkc_main candidate = {0};
		if (!hkbtkc_main_image(header, slide, &candidate)) return (struct hkbtkc_main){0};
		if (result.known) return (struct hkbtkc_main){0}; /* ambiguous executable */
		candidate.index = i;
		result = candidate;
	}
	return result;
}

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
	struct hkbtkc_main main = hkbtkc_find_main();
	hkbtkc_emit("HKBTKC: v2 start pid %d main 0x%llx slide 0x%llx known %u index %u console_errno %d\n",
	    getpid(), (unsigned long long)main.header, (unsigned long long)main.slide,
	    main.known, main.index, console_errno);
	hkbtkc_emit("HKBTKC: v2 main_uuid pid %d uuid %s\n", getpid(), main.known ? main.uuid : "unknown");
	__atomic_store_n(&hkbtkc_active, 1, __ATOMIC_RELEASE);
	errno = saved_errno;
}
#endif
