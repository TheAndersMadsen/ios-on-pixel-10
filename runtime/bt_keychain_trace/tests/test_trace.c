/* SPDX-License-Identifier: MIT */
#define HKBTKC_ENABLED 1
#define HKBTKC_HOST_TEST 1
#include "../trace.c"
#undef getenv
#undef getprogname
#undef open
#undef write
#include <assert.h>
#include <pthread.h>

static const char *test_env, *test_name = "bluetoothd";
static unsigned int opened, entered, returned, started, forwarded;
static unsigned int entries[HKBTKC_LIMIT + 1], returns[HKBTKC_LIMIT + 1];
static int fail_console, fail_write, partial_write;
static char query_token, attrs_token, result_token;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

const void *_dyld_get_image_header(unsigned int i) { assert(i == 0); return (void *)0x101000000; }
intptr_t _dyld_get_image_vmaddr_slide(unsigned int i) { assert(i == 0); return 0x1000000; }
const char *hkbtkc_test_getenv(const char *s) { assert(strcmp(s, "HK_BT_KEYCHAIN_TRACE") == 0); return test_env; }
const char *hkbtkc_test_getprogname(void) { return test_name; }
int hkbtkc_test_open(const char *s, int flags, ...)
{
	assert(strcmp(s, "/dev/console") == 0 && (flags & O_NONBLOCK));
	opened++;
	if (fail_console) { errno = EACCES; return -1; }
	return 87;
}

ssize_t hkbtkc_test_write(int fd, const void *buf, size_t size)
{
	assert(fd == 87 || fd == STDERR_FILENO);
	assert(size < 256);
	if (fail_write) { errno = EAGAIN; return -1; }
	if (partial_write) { errno = EDOM; return 1; }
	char line[256]; memcpy(line, buf, size); line[size] = 0;
	assert(!strstr(line, "SECRET") && !strstr(line, "BluetoothGlobal"));
	pthread_mutex_lock(&mutex);
	unsigned int id = 0;
	int pid = 0;
	char operation[16];
	if (strstr(line, " v1 start ")) {
		assert(strstr(line, "main 0x101000000 slide 0x1000000")); started++;
	} else {
		assert(sscanf(line, "HKBTKC: pid %d id %u %15s", &pid, &id, operation) == 3 && pid == getpid());
		assert(id > 0 && id <= HKBTKC_LIMIT);
		if (strstr(line, " enter ")) { entered++; entries[id]++; }
		else { assert(strstr(line, " return status ")); returned++; returns[id]++; }
	}
	pthread_mutex_unlock(&mutex);
	errno = EDOM;
	return (ssize_t)size;
}

static void seen(CFDictionaryRef q)
{
	assert(q == &query_token && errno == EBUSY);
	__atomic_add_fetch(&forwarded, 1, __ATOMIC_RELAXED);
	errno = ERANGE;
}
OSStatus SecItemCopyMatching(CFDictionaryRef q, CFTypeRef *r) { seen(q); if (r) *r = &result_token; return -25300; }
OSStatus SecItemAdd(CFDictionaryRef q, CFTypeRef *r) { seen(q); if (r) *r = &result_token; return -34018; }
OSStatus SecItemUpdate(CFDictionaryRef q, CFDictionaryRef a) { seen(q); assert(a == &attrs_token); return -25308; }
OSStatus SecItemDelete(CFDictionaryRef q) { seen(q); return 0; }

static void reset(void)
{
	test_env = NULL; test_name = "bluetoothd";
	opened = entered = returned = started = forwarded = 0;
	hkbtkc_active = hkbtkc_records = hkbtkc_lost = 0; hkbtkc_fd = -1;
	fail_console = fail_write = partial_write = 0;
	memset(entries, 0, sizeof(entries)); memset(returns, 0, sizeof(returns));
}

static void calls(void)
{
	CFTypeRef result = NULL;
	errno = EBUSY; assert(hk_bt_SecItemCopyMatching(&query_token, &result) == -25300);
	assert(errno == ERANGE && result == &result_token);
	result = NULL;
	errno = EBUSY; assert(hk_bt_SecItemAdd(&query_token, &result) == -34018);
	assert(errno == ERANGE && result == &result_token);
	errno = EBUSY; assert(hk_bt_SecItemUpdate(&query_token, &attrs_token) == -25308); assert(errno == ERANGE);
	errno = EBUSY; assert(hk_bt_SecItemDelete(&query_token) == 0); assert(errno == ERANGE);
}

static void *worker(void *unused) { (void)unused; calls(); return NULL; }

int main(void)
{
	reset(); hkbtkc_init(); calls();
	assert(opened == 0 && entered == 0 && forwarded == 4);
	test_env = "true"; hkbtkc_init(); assert(opened == 0);
	test_env = "1"; test_name = "otherd"; hkbtkc_init(); assert(opened == 0);
	test_name = "bluetoothd"; errno = ENOENT; hkbtkc_init();
	assert(errno == ENOENT && opened == 1 && started == 1);
	calls(); assert(entered == 4 && returned == 4 && forwarded == 8);
	reset(); test_env = "1"; fail_console = 1; hkbtkc_init();
	assert(hkbtkc_fd == STDERR_FILENO && started == 1); calls();
	fail_write = 1; calls(); assert(hkbtkc_lost == 8 && forwarded == 8);
	fail_write = 0; partial_write = 1; calls();
	assert(hkbtkc_lost == 16 && forwarded == 12);
	reset(); test_env = "1"; hkbtkc_init();
	pthread_t workers[32];
	for (unsigned int i = 0; i < 32; i++) assert(pthread_create(&workers[i], NULL, worker, NULL) == 0);
	for (unsigned int i = 0; i < 32; i++) assert(pthread_join(workers[i], NULL) == 0);
	assert(hkbtkc_records == 64 && entered == 64 && returned == 64 && forwarded == 128);
	for (unsigned int i = 1; i <= HKBTKC_LIMIT; i++) assert(entries[i] == 1 && returns[i] == 1);
	calls(); assert(forwarded == 132 && entered == 64 && hkbtkc_lost == 0);
	puts("PASS actual Security observer: disabled/filter/forward/status/errno/loss/concurrent bound");
	return 0;
}
