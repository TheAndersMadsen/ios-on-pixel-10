/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef const void *CFDictionaryRef;
typedef const void *CFTypeRef;
typedef int32_t OSStatus;
OSStatus SecItemCopyMatching(CFDictionaryRef, CFTypeRef *);
OSStatus SecItemAdd(CFDictionaryRef, CFTypeRef *);
OSStatus SecItemUpdate(CFDictionaryRef, CFDictionaryRef);
OSStatus SecItemDelete(CFDictionaryRef);
const void *_dyld_get_image_header(unsigned int);
intptr_t _dyld_get_image_vmaddr_slide(unsigned int);
const char *hkbtkc_test_getenv(const char *);
const char *hkbtkc_test_getprogname(void);
int hkbtkc_test_open(const char *, int, ...);
ssize_t hkbtkc_test_write(int, const void *, size_t);
#define getenv hkbtkc_test_getenv
#define getprogname hkbtkc_test_getprogname
#define open hkbtkc_test_open
#define write hkbtkc_test_write
