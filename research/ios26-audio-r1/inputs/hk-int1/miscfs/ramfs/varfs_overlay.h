/*
 * The boot image's overlay for /private/var. No kernel types: the host test includes it, and tools/mkoverlay.py writes it.
 *
 * The blob, little endian, 8-byte aligned throughout:
 *   header   char magic[8]; u32 total_len; u32 count; u64 fnv1a over the bytes after the header
 *   entry    u8 type; u8 group; u8 pad[2] = 0; u32 mode; u32 uid; u32 gid; u32 path_len; u32 data_len
 *            then the path and a NUL, zeros to 8; then the data, zeros to 8
 *
 * group is a bit number, 0..31. The boot-arg hk_overlay=MASK picks which groups apply, so one blob can carry files that
 * are tried on separate boots. A later entry for the same path wins: bits for two versions of a file give the later one.
 *
 * Types:
 *   d  directory: made, or if there, given this mode and owner
 *   f  file: replaces whatever file or link is there; data is its bytes
 *   l  symlink: replaces whatever file or link is there; data is its target, no NUL
 *   x  remove a file, a link or an empty directory; missing is fine
 *   c  exec rule, nothing on disk: path is hk_deny or hk_env, data is text appended to that rule
 *
 * Paths are under /private/var/ with no empty, . or .. component (varfs_tsv_path_ok). Parents come first: nothing is
 * made implicitly. Anything else is an error for the whole blob, found before the first entry is applied.
 *
 * Covers: a group can put a ramfs over a directory of the read-only root, on BLAZER:
 *   l /private/var/hkcover/NAME.cover   its target is the directory to cover
 *   d /private/var/hkcover/NAME         and under it the cover's d and f entries
 * Nothing under /private/var/hkcover goes into /private/var. hk_overlay picks the group as usual. A kernel without this
 * code unpacks them there instead, which is harmless and shows as no "hkcover:" line.
 */
#ifndef VARFS_OVERLAY_H
#define VARFS_OVERLAY_H

#include <miscfs/ramfs/varfs_tsv.h>

#define HKOV_MAGIC              "HKVAROV1"
#define HKOV_HEADER_SIZE        24u
#define HKOV_ENTRY_SIZE         24u
#define HKOV_TOTAL_MAX          (48u << 20)     /* the boot image can't hold more: 45 MB of margin */
#define HKOV_COUNT_MAX          4096u
#define HKOV_COVER_DIR          "/private/var/hkcover"
#define HKOV_COVER_DIR_LEN      20u
#define HKOV_COVER_SUFFIX       ".cover"
#define HKOV_COVER_SUFFIX_LEN   6u
#define HKOV_COVERS_MAX         8u

struct hkov_entry {
	char            type;
	unsigned int    group;
	unsigned int    mode, uid, gid;
	const char     *path;           /* NUL-terminated, inside the blob */
	unsigned int    path_len;
	const unsigned char *data;      /* inside the blob */
	unsigned int    data_len;
};

static inline unsigned int
hkov_u32(const unsigned char *p)
{
	return (unsigned int)p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}

static inline unsigned long long
hkov_u64(const unsigned char *p)
{
	return (unsigned long long)hkov_u32(p) | (unsigned long long)hkov_u32(p + 4) << 32;
}

static inline unsigned long long
hkov_fnv1a(const unsigned char *p, unsigned long len)
{
	unsigned long long h = 0xcbf29ce484222325ull;

	for (unsigned long i = 0; i < len; i++) {
		h = (h ^ p[i]) * 0x100000001b3ull;
	}
	return h;
}

static inline int
hkov_zeros(const unsigned char *p, unsigned long len)
{
	for (unsigned long i = 0; i < len; i++) {
		if (p[i] != 0) {
			return 0;
		}
	}
	return 1;
}

static inline int
hkov_same(const char *a, const char *b, unsigned int n)
{
	for (unsigned int i = 0; i < n; i++) {
		if (a[i] != b[i]) {
			return 0;
		}
	}
	return 1;
}

/*
 * The entry at *off, which moves past it. 1: an entry. -1: *why says what is wrong. The caller knows the count, and stops
 * when off reaches total. total has been checked to fit the blob.
 */
static inline int
hkov_next(const unsigned char *blob, unsigned long total, unsigned long *off, struct hkov_entry *e, const char **why)
{
	unsigned long at = *off, path_off, path_end, data_off, data_end;
	const unsigned char *h;

	if (at > total || total - at < HKOV_ENTRY_SIZE) {
		*why = "entry past the end";
		return -1;
	}
	h = blob + at;
	e->type = (char)h[0];
	e->group = h[1];
	if (e->group > 31) {
		*why = "group above 31";
		return -1;
	}
	if (h[2] != 0 || h[3] != 0) {
		*why = "pad not zero";
		return -1;
	}
	e->mode = hkov_u32(h + 4);
	e->uid = hkov_u32(h + 8);
	e->gid = hkov_u32(h + 12);
	e->path_len = hkov_u32(h + 16);
	e->data_len = hkov_u32(h + 20);
	if (e->type != 'd' && e->type != 'f' && e->type != 'l' && e->type != 'x' && e->type != 'c') {
		*why = "unknown type";
		return -1;
	}
	if ((e->mode & ~07777u) != 0) {
		*why = "mode above 07777";
		return -1;
	}

	path_off = at + HKOV_ENTRY_SIZE;
	if (e->path_len == 0 || e->path_len >= VARFS_PATH_MAX || total - path_off <= e->path_len) {
		*why = "bad path length";
		return -1;
	}
	path_end = path_off + e->path_len + 1;
	data_off = (path_end + 7) & ~7ul;
	if (data_off > total) {
		*why = "path past the end";
		return -1;
	}
	if (e->data_len > total - data_off) {
		*why = "data past the end";
		return -1;
	}
	data_end = data_off + e->data_len;
	if (data_end > ((data_end + 7) & ~7ul) || ((data_end + 7) & ~7ul) > total) {
		*why = "padding past the end";
		return -1;
	}
	if (blob[path_off + e->path_len] != 0 || !hkov_zeros(blob + path_end, data_off - path_end) ||
	    !hkov_zeros(blob + data_end, ((data_end + 7) & ~7ul) - data_end)) {
		*why = "padding not zero";
		return -1;
	}
	for (unsigned long i = 0; i < e->path_len; i++) {
		if (blob[path_off + i] == 0) {
			*why = "NUL in path";
			return -1;
		}
	}
	e->path = (const char *)(blob + path_off);
	e->data = blob + data_off;

	switch (e->type) {
	case 'c':
		if (e->data_len == 0) {
			*why = "empty rule";
			return -1;
		}
		if (!(e->path_len == 7 && hkov_same(e->path, "hk_deny", 7)) && !(e->path_len == 6 && hkov_same(e->path, "hk_env", 6))) {
			*why = "unknown rule";
			return -1;
		}
		for (unsigned long i = 0; i < e->data_len; i++) {
			if (e->data[i] == 0) {
				*why = "NUL in rule";
				return -1;
			}
		}
		break;
	case 'l':
		if (e->data_len == 0 || e->data_len >= VARFS_PATH_MAX) {
			*why = "bad link target";
			return -1;
		}
		for (unsigned long i = 0; i < e->data_len; i++) {
			if (e->data[i] == 0) {
				*why = "NUL in link target";
				return -1;
			}
		}
		__attribute__((fallthrough));
	case 'f':
		if (!varfs_tsv_path_ok(e->path, e->path_len)) {
			*why = "bad path";
			return -1;
		}
		break;
	default:
		if (e->data_len != 0) {
			*why = "data on d or x";
			return -1;
		}
		if (!varfs_tsv_path_ok(e->path, e->path_len)) {
			*why = "bad path";
			return -1;
		}
		break;
	}
	*off = (data_end + 7) & ~7ul;
	return 1;
}

/*
 * The whole blob, before anything is applied. size is what the boot image gave it, which may be rounded up. NULL if good;
 * *total_out is the blob's own length, *count_out its entries.
 */
static inline const char *
hkov_check(const unsigned char *blob, unsigned long size, unsigned long *total_out, unsigned int *count_out, unsigned long long *hash_out)
{
	const char *magic = HKOV_MAGIC, *why = "";
	unsigned long total, off = HKOV_HEADER_SIZE;
	unsigned int count;
	struct hkov_entry e;

	if (size < HKOV_HEADER_SIZE) {
		return "smaller than a header";
	}
	for (unsigned int i = 0; i < 8; i++) {
		if ((unsigned char)magic[i] != blob[i]) {
			return "bad magic";
		}
	}
	total = hkov_u32(blob + 8);
	count = hkov_u32(blob + 12);
	if (total < HKOV_HEADER_SIZE || total > size || total > HKOV_TOTAL_MAX || (total & 7) != 0) {
		return "bad total length";
	}
	if (count == 0 || count > HKOV_COUNT_MAX) {
		return "bad count";
	}
	if (hkov_fnv1a(blob + HKOV_HEADER_SIZE, total - HKOV_HEADER_SIZE) != hkov_u64(blob + 16)) {
		return "hash differs";
	}
	for (unsigned int i = 0; i < count; i++) {
		if (hkov_next(blob, total, &off, &e, &why) != 1) {
			return why;
		}
	}
	if (off != total) {
		return "bytes after the last entry";
	}
	*total_out = total;
	*count_out = count;
	*hash_out = hkov_u64(blob + 16);
	return (const char *)0;
}

/* The groups a checked blob holds, as a mask for hk_overlay=. */
static inline unsigned int
hkov_groups(const unsigned char *blob, unsigned long total, unsigned int count)
{
	unsigned long off = HKOV_HEADER_SIZE;
	unsigned int groups = 0;
	const char *why = "";
	struct hkov_entry e;

	for (unsigned int i = 0; i < count && hkov_next(blob, total, &off, &e, &why) == 1; i++) {
		groups |= 1u << e.group;
	}
	return groups;
}

/* Is this entry, of a checked blob, overridden by a later selected entry for the same path? */
static inline int
hkov_overridden(const unsigned char *blob, unsigned long total, unsigned int count, unsigned int index, unsigned long next_off,
    const struct hkov_entry *e, unsigned int mask)
{
	unsigned long off = next_off;
	const char *why = "";
	struct hkov_entry later;

	for (unsigned int i = index + 1; i < count && hkov_next(blob, total, &off, &later, &why) == 1; i++) {
		if ((mask & (1u << later.group)) != 0 && later.type != 'c' && later.path_len == e->path_len &&
		    hkov_same(later.path, e->path, e->path_len)) {
			return 1;
		}
	}
	return 0;
}

/* Is this entry part of a cover, so not for /private/var? */
static inline int
hkov_is_cover(const struct hkov_entry *e)
{
	return e->type != 'c' && e->path_len >= HKOV_COVER_DIR_LEN && hkov_same(e->path, HKOV_COVER_DIR, HKOV_COVER_DIR_LEN) &&
	       (e->path_len == HKOV_COVER_DIR_LEN || e->path[HKOV_COVER_DIR_LEN] == '/');
}

/* Does this entry name a cover? Then *from_len is the length of /private/var/hkcover/NAME, the start of its path. */
static inline int
hkov_cover_head(const struct hkov_entry *e, unsigned int *from_len)
{
	unsigned int first = HKOV_COVER_DIR_LEN + 1;

	if (e->type != 'l' || !hkov_is_cover(e) || e->path_len <= first + HKOV_COVER_SUFFIX_LEN ||
	    !hkov_same(e->path + e->path_len - HKOV_COVER_SUFFIX_LEN, HKOV_COVER_SUFFIX, HKOV_COVER_SUFFIX_LEN)) {
		return 0;
	}
	for (unsigned int i = first; i < e->path_len; i++) {
		if (e->path[i] == '/') {
			return 0;
		}
	}
	*from_len = e->path_len - HKOV_COVER_SUFFIX_LEN;
	return 1;
}

/*
 * The selected groups' covers, on a checked blob, before anything is applied. NULL if good. *covers_out is how many.
 * Each head's target is an absolute path with no empty, . or .. component and outside /private/var. Under the cover directory, only
 * /private/var/hkcover itself, heads, and d and f entries of a head's NAME in the same group, after that head.
 */
static inline const char *
hkov_cover_check(const unsigned char *blob, unsigned long total, unsigned int count, unsigned int mask, unsigned int *covers_out)
{
	unsigned long off = HKOV_HEADER_SIZE;
	const char *why = "";
	struct hkov_entry e;
	unsigned int covers = 0;

	for (unsigned int i = 0; i < count; i++) {
		unsigned int from_len = 0;

		if (hkov_next(blob, total, &off, &e, &why) != 1) {
			return why;
		}
		if ((mask & (1u << e.group)) == 0 || !hkov_is_cover(&e)) {
			continue;
		}
		if (hkov_cover_head(&e, &from_len)) {
			unsigned int at = 0;

			if (++covers > HKOV_COVERS_MAX) {
				return "more covers than the limit";
			}
			if (e.data_len < 2 || e.data[0] != '/' || e.data[e.data_len - 1] == '/') {
				return "cover target isn't an absolute path";
			}
			while (at < e.data_len) {
				unsigned int w = at + 1, n;

				while (w < e.data_len && e.data[w] != '/') {
					w++;
				}
				n = w - at - 1;
				if (n == 0 || (n == 1 && e.data[at + 1] == '.') || (n == 2 && e.data[at + 1] == '.' && e.data[at + 2] == '.')) {
					return "cover target has an empty, . or .. component";
				}
				at = w;
			}
			if (e.data_len >= 12 && hkov_same((const char *)e.data, "/private/var", 12) && (e.data_len == 12 || e.data[12] == '/')) {
				return "cover target is inside /private/var";
			}
			continue;
		}
		if (e.path_len == HKOV_COVER_DIR_LEN) {
			if (e.type != 'd') {
				return HKOV_COVER_DIR " isn't a directory entry";
			}
			continue;
		}
		if (e.type != 'd' && e.type != 'f') {
			return "only d and f in a cover";
		}
		/* NAME, or NAME/...: some head of this group, earlier in the blob, must name it */
		{
			unsigned long o2 = HKOV_HEADER_SIZE;
			struct hkov_entry h;
			int found = 0;

			for (unsigned int j = 0; j < i && !found; j++) {
				unsigned int fl = 0;

				if (hkov_next(blob, total, &o2, &h, &why) != 1) {
					return why;
				}
				found = h.group == e.group && hkov_cover_head(&h, &fl) && e.path_len >= fl && hkov_same(e.path, h.path, fl) &&
				    (e.path_len == fl || e.path[fl] == '/');
			}
			if (!found) {
				return "cover entry with no head before it in its group";
			}
		}
	}
	*covers_out = covers;
	return (const char *)0;
}

#endif /* VARFS_OVERLAY_H */
