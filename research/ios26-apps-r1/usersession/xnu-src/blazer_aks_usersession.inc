/*
 * hackios: software AKS user-session answers for SweetKeyStore (MIT, original).
 *
 * Gate: compile BLAZER_AKS_USERSESSION and boot-arg blazer_aks_usersession=1. Off: every selector below stays
 * kIOReturnUnsupported, as before. No XNU types here; the host test includes this file as C.
 *
 * Scope: the local user session only (MobileKeyBag MKBUserSession*, usermanagerd's per-user persona setup through
 * keybagd). There is no SEP and no data protection on this device (/private/var is a RAM varfs mounted without
 * cprotect), so the "user keybag" holds no keys: it is a 16-byte opaque record. Handles are not secrets. Nothing here
 * creates, emulates or answers for an Apple identity, attestation or escrow; those selectors stay unsupported.
 *
 * Selectors and shapes (iOS 26 AppleKeyStore.framework, dyld cache dsc-r6; IOConnectCallMethod(conn, sel, scalars_in,
 * n, struct_in, len, scalars_out, &n, struct_out, &len)):
 *   2   aks_create_bag          scalars in (type...), struct in (passcode, may be empty) -> scalar out handle
 *   3   aks_save_bag            scalar in handle -> struct out bag bytes (cap 0x8000)
 *   6   aks_load_bag            struct in bag bytes -> scalar out handle          (_aks_load_bag 0x1e4b35044)
 *   65  aks_set_keybag_for_volume_with_cookie_persona  scalars in, struct in -> nothing
 *   96  aks_keybag_persona_create         3 scalars {handle, ...}, struct in (DER) -> nothing (0x1e4b365f4)
 *   117 aks_keybag_persona_create_with_flags  as 96 plus flags -> nothing
 *   97  aks_keybag_persona_list   scalar in handle -> struct out (cap 0x2000)       (0x1e4b36808)
 *   98  aks_keybag_persona_delete scalars in, struct in -> nothing
 * aks_get_system (14), aks_set_system (5), aks_unload_bag (4), aks_unload_session_bags (55) are already answered by
 * the base stub (handle 0, success).
 */
#ifndef BLAZER_AKS_USERSESSION_INC
#define BLAZER_AKS_USERSESSION_INC

#define AUS_OK          0
#define AUS_UNHANDLED   1   /* not a user-session selector: the caller keeps its own answer */
#define AUS_BAD_ARG     2
#define AUS_NO_SPACE    3

#define AUS_USER_HANDLE 1u  /* the one user bag handle this stub hands out (the system bag is 0) */
#define AUS_BAG_LEN     16u

struct aus_call {
	unsigned int selector;
	unsigned int scalars_in;        /* count */
	const unsigned long long *scalar_in;
	unsigned int struct_in_len;
	unsigned int scalars_out_cap;   /* count the caller can take */
	unsigned int struct_out_cap;    /* bytes the caller can take */
};

struct aus_result {
	unsigned long long scalar_out[1];
	unsigned int scalars_out;
	unsigned char struct_out[AUS_BAG_LEN];
	unsigned int struct_out_len;
};

/* The opaque "user bag": magic, version, handle. Loading accepts only this format, so a real Apple bag is refused. */
static const unsigned char aus_bag_magic[8] = { 'H', 'K', 'U', 'S', 'B', 'A', 'G', '1' };

static void
aus_bag_bytes(unsigned char out[AUS_BAG_LEN])
{
	unsigned int i;
	for (i = 0; i < 8; i++) {
		out[i] = aus_bag_magic[i];
	}
	for (i = 8; i < AUS_BAG_LEN; i++) {
		out[i] = 0;
	}
	out[8] = (unsigned char)AUS_USER_HANDLE;
}

static int
aus_is_selector(unsigned int sel)
{
	return sel == 2 || sel == 3 || sel == 6 || sel == 65 || sel == 96 || sel == 97 || sel == 98 || sel == 117;
}

/*
 * Decide one call. bag_in is the struct input (only read for selector 6). On AUS_OK, r holds the outputs; on any
 * other status r->scalars_out and r->struct_out_len are 0.
 */
static int
aus_call(const struct aus_call *c, const unsigned char *bag_in, struct aus_result *r)
{
	unsigned int i;

	r->scalars_out = 0;
	r->struct_out_len = 0;
	if (!aus_is_selector(c->selector)) {
		return AUS_UNHANDLED;
	}
	switch (c->selector) {
	case 2:     /* create_bag: a handle */
		if (c->scalars_out_cap < 1) {
			return AUS_BAD_ARG;
		}
		r->scalar_out[0] = AUS_USER_HANDLE;
		r->scalars_out = 1;
		return AUS_OK;
	case 3:     /* save_bag: the opaque record for our handle only */
		if (c->scalars_in < 1 || c->scalar_in[0] != AUS_USER_HANDLE) {
			return AUS_BAD_ARG;
		}
		if (c->struct_out_cap < AUS_BAG_LEN) {
			return AUS_NO_SPACE;
		}
		aus_bag_bytes(r->struct_out);
		r->struct_out_len = AUS_BAG_LEN;
		return AUS_OK;
	case 6: {   /* load_bag: only our own record */
		unsigned char want[AUS_BAG_LEN];
		if (c->scalars_out_cap < 1 || bag_in == 0 || c->struct_in_len != AUS_BAG_LEN) {
			return AUS_BAD_ARG;
		}
		aus_bag_bytes(want);
		for (i = 0; i < AUS_BAG_LEN; i++) {
			if (bag_in[i] != want[i]) {
				return AUS_BAD_ARG;
			}
		}
		r->scalar_out[0] = AUS_USER_HANDLE;
		r->scalars_out = 1;
		return AUS_OK;
	}
	case 97:    /* persona_list: an empty DER SEQUENCE (no persona keys are held) */
		if (c->scalars_in < 1) {
			return AUS_BAD_ARG;
		}
		if (c->struct_out_cap < 2) {
			return AUS_NO_SPACE;
		}
		r->struct_out[0] = 0x30;
		r->struct_out[1] = 0x00;
		r->struct_out_len = 2;
		return AUS_OK;
	case 96:
	case 117:   /* persona key create: needs the bag handle and the DER request */
		if (c->scalars_in < 1 || c->struct_in_len == 0) {
			return AUS_BAD_ARG;
		}
		return AUS_OK;
	default:    /* 65 set_keybag_for_volume_with_cookie_persona, 98 persona_delete: accepted, nothing kept */
		if (c->scalars_in < 1) {
			return AUS_BAD_ARG;
		}
		return AUS_OK;
	}
}

static const char *
aus_status_name(int st)
{
	switch (st) {
	case AUS_OK: return "ok";
	case AUS_UNHANDLED: return "unhandled";
	case AUS_BAD_ARG: return "bad argument";
	case AUS_NO_SPACE: return "no space";
	default: return "?";
	}
}

#endif /* BLAZER_AKS_USERSESSION_INC */
