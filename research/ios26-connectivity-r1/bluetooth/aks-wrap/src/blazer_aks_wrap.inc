/* SPDX-License-Identifier: MIT
 * hackios: software aks_wrap_key / aks_unwrap_key for SWEET's built-in AppleKeyStore (SweetKeyStore.cpp).
 *
 * Why: on the phone (bt-fast-r1, a7-ios-system-r3) and in QEMU (keychain-guest-r3) every
 * "SWEET AKS: securityd sel 10 arg0 0 in 2/32 out 1/128 -> 0xe00002c7" is securityd failing to wrap a
 * keychain item key, so SecItemAdd returns errSecNotAvailable (-25291) system-wide and bluetoothd exits(1)
 * at its LE root-key startup. iOS 26 libaks (dsc-r6 AppleKeyStore) calls:
 *   aks_wrap_key:   IOConnectCallMethod(c, 10, {handle, class}, 2, key, key_len, &class_out, 1, wrapped, &wrapped_len)
 *   aks_unwrap_key: IOConnectCallMethod(c, 11, {handle, class}, 2, wrapped, wrapped_len, NULL, 0, key, &key_len)
 *
 * What: deterministic authenticated encryption (SIV over HMAC-SHA256, no AES needed: XNU has cchmac and
 * ccsha256_ltc_di built in). Wrapped blob, version 1:
 *   'h' 'k' 0x01 key_len | tag[16] | key XOR KS
 *   tag = HMAC(mac_key, "HKW1" | hdr | handle(LE64) | class(LE32) | key)[0..16]
 *   KS  = HMAC(enc_key, tag | 0x00) | HMAC(enc_key, tag | 0x01)        (keys up to 64 bytes)
 *   mac_key = HMAC(secret, "hackios aks wrap v1 mac"), enc_key = HMAC(secret, "hackios aks wrap v1 enc")
 * The secret is the caller's (per-boot random in the kernel). Only the system bag (handle 0) is served; the
 * class is echoed in class_out and bound into the tag, so unwrapping under another class or handle fails.
 * Nothing about keys is logged. No SEP: protection is only as good as the secret's custody (PLAN.md).
 *
 * No XNU types: compiled as C by the host test and as C++ inside SweetKeyStore.cpp.
 */
#ifndef BLAZER_AKS_WRAP_INC
#define BLAZER_AKS_WRAP_INC

#define AW_SECRET       32u
#define AW_HDR          4u
#define AW_TAG          16u
#define AW_KEY_MAX      64u
#define AW_OVERHEAD     (AW_HDR + AW_TAG)
#define AW_SYSTEM_BAG   0ull

enum aw_status {
	AW_OK = 0, AW_BAD_ARG, AW_NO_SPACE, AW_BAD_HANDLE, AW_BAD_CLASS, AW_NOT_READY, AW_DECODE, AW_AUTH,
};

typedef void (*aw_hmac_fn)(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len, uint8_t out[32]);

struct aw_ctx {
	uint8_t mac_key[32];
	uint8_t enc_key[32];
	aw_hmac_fn hmac;
	int ready;
};

static void
aw_zero(void *p, size_t n)
{
	volatile uint8_t *v = (volatile uint8_t *)p;

	while (n-- > 0) {
		*v++ = 0;
	}
}

static int
aw_init(struct aw_ctx *c, aw_hmac_fn hmac, const uint8_t secret[AW_SECRET])
{
	static const char mac_label[] = "hackios aks wrap v1 mac";
	static const char enc_label[] = "hackios aks wrap v1 enc";

	if (c == NULL || hmac == NULL || secret == NULL) {
		return AW_BAD_ARG;
	}
	hmac(secret, AW_SECRET, (const uint8_t *)mac_label, sizeof(mac_label) - 1, c->mac_key);
	hmac(secret, AW_SECRET, (const uint8_t *)enc_label, sizeof(enc_label) - 1, c->enc_key);
	c->hmac = hmac;
	c->ready = 1;
	return AW_OK;
}

static int
aw_check(const struct aw_ctx *c, uint64_t handle, uint64_t key_class)
{
	if (c == NULL || !c->ready) {
		return AW_NOT_READY;
	}
	if (handle != AW_SYSTEM_BAG) {
		return AW_BAD_HANDLE;
	}
	/* libaks passes keyclass_t (int) sign-extended; class id is the low 5 bits and 0 is no class */
	if (key_class > 0xffffffffull || (key_class & 0x1fu) == 0) {
		return AW_BAD_CLASS;
	}
	return AW_OK;
}

/* tag over header, handle, class and plaintext key */
static void
aw_tag(const struct aw_ctx *c, const uint8_t hdr[AW_HDR], uint64_t handle, uint64_t key_class,
    const uint8_t *key, uint32_t key_len, uint8_t tag[AW_TAG])
{
	uint8_t msg[4 + AW_HDR + 8 + 4 + AW_KEY_MAX], full[32];
	uint32_t n = 0;

	msg[n++] = 'H'; msg[n++] = 'K'; msg[n++] = 'W'; msg[n++] = '1';
	for (uint32_t i = 0; i < AW_HDR; i++) {
		msg[n++] = hdr[i];
	}
	for (uint32_t i = 0; i < 8; i++) {
		msg[n++] = (uint8_t)(handle >> (8 * i));
	}
	for (uint32_t i = 0; i < 4; i++) {
		msg[n++] = (uint8_t)(key_class >> (8 * i));
	}
	for (uint32_t i = 0; i < key_len; i++) {
		msg[n++] = key[i];
	}
	c->hmac(c->mac_key, sizeof(c->mac_key), msg, n, full);
	for (uint32_t i = 0; i < AW_TAG; i++) {
		tag[i] = full[i];
	}
	aw_zero(msg, sizeof(msg));
	aw_zero(full, sizeof(full));
}

/* dst = src XOR keystream(tag) */
static void
aw_xor(const struct aw_ctx *c, const uint8_t tag[AW_TAG], const uint8_t *src, uint8_t *dst, uint32_t len)
{
	uint8_t in[AW_TAG + 1], ks[32];

	for (uint32_t i = 0; i < AW_TAG; i++) {
		in[i] = tag[i];
	}
	for (uint32_t block = 0; block * 32 < len; block++) {
		in[AW_TAG] = (uint8_t)block;
		c->hmac(c->enc_key, sizeof(c->enc_key), in, sizeof(in), ks);
		for (uint32_t i = 0; i < 32 && block * 32 + i < len; i++) {
			dst[block * 32 + i] = src[block * 32 + i] ^ ks[i];
		}
	}
	aw_zero(ks, sizeof(ks));
}

static int
aw_wrap(const struct aw_ctx *c, uint64_t handle, uint64_t key_class, const uint8_t *key, uint32_t key_len,
    uint8_t *out, uint32_t out_cap, uint32_t *out_len)
{
	int st = aw_check(c, handle, key_class);

	if (st != AW_OK) {
		return st;
	}
	if (key == NULL || out == NULL || out_len == NULL || key_len == 0 || key_len > AW_KEY_MAX) {
		return AW_BAD_ARG;
	}
	if (out_cap < AW_OVERHEAD + key_len) {
		return AW_NO_SPACE;
	}
	out[0] = 'h';
	out[1] = 'k';
	out[2] = 1;
	out[3] = (uint8_t)key_len;
	aw_tag(c, out, handle, key_class, key, key_len, out + AW_HDR);
	aw_xor(c, out + AW_HDR, key, out + AW_OVERHEAD, key_len);
	*out_len = AW_OVERHEAD + key_len;
	return AW_OK;
}

static int
aw_unwrap(const struct aw_ctx *c, uint64_t handle, uint64_t key_class, const uint8_t *in, uint32_t in_len,
    uint8_t *key, uint32_t key_cap, uint32_t *key_len)
{
	uint8_t plain[AW_KEY_MAX], tag[AW_TAG];
	uint32_t n;
	uint8_t diff = 0;
	int st = aw_check(c, handle, key_class);

	if (st != AW_OK) {
		return st;
	}
	if (in == NULL || key == NULL || key_len == NULL) {
		return AW_BAD_ARG;
	}
	if (in_len < AW_OVERHEAD + 1 || in[0] != 'h' || in[1] != 'k' || in[2] != 1) {
		return AW_DECODE;
	}
	n = in[3];
	if (n == 0 || n > AW_KEY_MAX || in_len != AW_OVERHEAD + n) {
		return AW_DECODE;
	}
	if (key_cap < n) {
		return AW_NO_SPACE;
	}
	aw_xor(c, in + AW_HDR, in + AW_OVERHEAD, plain, n);
	aw_tag(c, in, handle, key_class, plain, n, tag);
	for (uint32_t i = 0; i < AW_TAG; i++) {
		diff |= (uint8_t)(tag[i] ^ in[AW_HDR + i]);
	}
	if (diff != 0) {
		aw_zero(plain, sizeof(plain));
		return AW_AUTH;
	}
	for (uint32_t i = 0; i < n; i++) {
		key[i] = plain[i];
	}
	*key_len = n;
	aw_zero(plain, sizeof(plain));
	aw_zero(tag, sizeof(tag));
	return AW_OK;
}

static const char *
aw_status_name(int st)
{
	static const char *const names[] = {
		"ok", "bad-arg", "no-space", "bad-handle", "bad-class", "not-ready", "decode", "auth",
	};
	return st >= 0 && st < (int)(sizeof(names) / sizeof(names[0])) ? names[st] : "?";
}
#endif /* BLAZER_AKS_WRAP_INC */
