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
static unsigned int opened, entered, returned, started, main_uuid, forwarded;
static unsigned int entries[HKBTKC_LIMIT + 1], returns[HKBTKC_LIMIT + 1];
static int fail_console, fail_write, partial_write;
static char query_token, attrs_token, result_token;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

static unsigned char images[3][131104];
static unsigned int image_count = 2, image_churn, image_reads;
static intptr_t bad_slide;
static unsigned int expected_main_known = 1;
static void put32(unsigned char *p, uint32_t n) { memcpy(p, &n, 4); }
static void put64(unsigned char *p, uint64_t n) { memcpy(p, &n, 8); }
static void image(unsigned int i, uint32_t type)
{
	unsigned char *p = images[i]; memset(p, 0, sizeof(images[i]));
	put32(p, 0xfeedfacf); put32(p + 4, 0x0100000c); put32(p + 12, type);
	put32(p + 16, 2); put32(p + 20, 96);
	put32(p + 32, 0x1b); put32(p + 36, 24);
	for (unsigned int n = 0; n < 16; n++) p[40 + n] = (unsigned char)(n + 1);
	put32(p + 56, 0x19); put32(p + 60, 72); memcpy(p + 64, "__TEXT", 7);
	put64(p + 80, type == 2 ? 0x100000000ULL : 0);
	put64(p + 88, 0x4000); put64(p + 104, 0x4000);
}
static void reset_images(void)
{
	image(0, 6); image(1, 2); image(2, 6);
	image_count = 2; image_churn = image_reads = 0; bad_slide = 0;
}
unsigned int _dyld_image_count(void) { return image_count; }
const void *_dyld_get_image_header(unsigned int i)
{
	assert(i < image_count && i < 3);
	if (image_churn && i == 1 && image_reads++) return images[2];
	return images[i];
}
intptr_t _dyld_get_image_vmaddr_slide(unsigned int i)
{
	assert(i < image_count && i < 3);
	return (intptr_t)((uintptr_t)images[i] - hkbtkc_u64(images[i] + 80)) + bad_slide;
}

static void image_checks(void)
{
	reset_images(); struct hkbtkc_main m = hkbtkc_find_main();
	assert(m.known && m.index == 1 && m.header == (uintptr_t)images[1]);
	assert(strcmp(m.uuid, "0102030405060708090a0b0c0d0e0f10") == 0);
	assert(m.header == 0x100000000ULL + (uintptr_t)m.slide);
	image(0, 2); image(1, 6); m = hkbtkc_find_main(); assert(m.known && m.index == 0);
	reset_images(); image(2, 2); image_count = 3; assert(!hkbtkc_find_main().known);
	reset_images(); image(1, 6); assert(!hkbtkc_find_main().known);
	reset_images(); image_count = 4097; assert(!hkbtkc_find_main().known);
	reset_images(); image_churn = 1; assert(!hkbtkc_find_main().known);
	reset_images(); bad_slide = 1; assert(!hkbtkc_find_main().known);
	for (unsigned int n = 0; n < 13; n++) {
		reset_images(); unsigned char *p = images[1];
		switch (n) {
		case 0: put32(p, 0); break;
		case 1: put32(p + 4, 0x01000007); break;
		case 2: put32(p + 16, 0); break;
		case 3: put32(p + 16, 4097); break;
		case 4: put32(p + 20, 131073); break;
		case 5: put32(p + 36, 0); break;
		case 6: put32(p + 36, 0xfffffff8); break;
		case 7: put32(p + 32, 0); break; /* missing UUID */
		case 8: memset(p + 40, 0, 16); break;
		case 9: put32(p + 120, 0xffffffff); break; /* section extent */
		case 10: put64(p + 96, 8); break; /* nonzero TEXT file offset */
		case 11: put64(p + 104, 64); break; /* commands outside TEXT */
		case 12: put32(p + 20, 104); break; /* unconsumed command bytes */
		}
		assert(!hkbtkc_find_main().known);
	}
	reset_images(); unsigned char *p = images[1];
	put32(p + 16, 3); put32(p + 20, 120); memcpy(p + 128, p + 32, 24);
	assert(!hkbtkc_find_main().known); /* duplicate UUID */
	reset_images(); struct hkbtkc_main v = {0};
	put64(p + 80, (uintptr_t)p + 4096); assert(hkbtkc_main_image(p, -4096, &v));
	put64(p + 80, UINT64_MAX); assert(!hkbtkc_main_image(p, 1, &v));
	put64(p + 80, 1); assert(!hkbtkc_main_image(p, INTPTR_MIN, &v));
	reset_images();
}
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
	if (strstr(line, " v2 start ")) {
		char wanted[128];
		if (expected_main_known) snprintf(wanted, sizeof(wanted), "main 0x%llx slide 0x%llx known 1 index 1",
		    (unsigned long long)(uintptr_t)images[1], (unsigned long long)_dyld_get_image_vmaddr_slide(1));
		else snprintf(wanted, sizeof(wanted), "main 0x0 slide 0x0 known 0 index 0");
		assert(strstr(line, wanted)); started++;
	} else if (strstr(line, " v2 main_uuid ")) {
		assert(strstr(line, expected_main_known ? "uuid 0102030405060708090a0b0c0d0e0f10" : "uuid unknown")); main_uuid++;
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
	opened = entered = returned = started = main_uuid = forwarded = 0;
	hkbtkc_active = hkbtkc_records = hkbtkc_lost = 0; hkbtkc_fd = -1;
	fail_console = fail_write = partial_write = 0;
	memset(entries, 0, sizeof(entries)); memset(returns, 0, sizeof(returns));
	reset_images();
	expected_main_known = 1;
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
	image_checks();
	reset(); test_env = "1"; expected_main_known = 0; image(1, 6); hkbtkc_init();
	assert(started == 1 && main_uuid == 1 && hkbtkc_active == 1);
	reset(); hkbtkc_init(); calls();
	assert(opened == 0 && entered == 0 && forwarded == 4);
	test_env = "true"; hkbtkc_init(); assert(opened == 0);
	test_env = "1"; test_name = "otherd"; hkbtkc_init(); assert(opened == 0);
	test_name = "bluetoothd"; errno = ENOENT; hkbtkc_init();
	assert(errno == ENOENT && opened == 1 && started == 1 && main_uuid == 1);
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
	puts("PASS actual Security observer: executable selection/UUID/bounds/ambiguity/churn; disabled/filter/forward/status/errno/loss/concurrent bound");
	return 0;
}
