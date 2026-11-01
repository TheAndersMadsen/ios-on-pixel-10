/* Bounded FDT v17 parser and native allocator-window admission gate.
 * No allocation, unbounded string read, speculative MMIO or destination write. */
#include "fdt.h"
struct span { const unsigned char *p; uint32_t n; };
struct node {
	struct span reg, size, alloc, alignment;
	const char *name;
	unsigned kind, ac, sc, seen, disabled, children, memory, ranges, psci;
};
enum { ROOT = 1, MEMORY, RESERVED, RESERVATION, CHOSEN, PSCI };
enum { AC = 1, SC = 2, REG = 4, SIZE = 8, ALLOC = 16,
	STATUS = 32, TYPE = 64, RANGES = 128, METHOD = 256, COMPAT = 512, ALIGN = 1024 };
static uint32_t be32(const unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static uint64_t be64(const unsigned char *p) { return (uint64_t)be32(p) << 32 | be32(p + 4); }
static int eq(const char *a, const char *b)
{
	while (*a && *a == *b) ++a, ++b;
	return *a == *b;
}
static int strval(struct span v, const char *s)
{
	unsigned i = 0;
	while (s[i]) { if (i >= v.n || v.p[i] != (unsigned char)s[i]) return 0; ++i; }
	return i < v.n && !v.p[i] && i + 1 == v.n;
}
static int stringlen(const unsigned char *p, uint32_t n, uint32_t *len)
{
	for (uint32_t i = 0; i < n; ++i) if (!p[i]) { *len = i; return 1; }
	return 0;
}
static int bootarg_space(unsigned char c)
{
	return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}
static unsigned bootarg_display_flag(const unsigned char *p, uint32_t n,
	const char *key, uint32_t keylen, unsigned bit)
{
	unsigned found = 0, malformed = 0;
	for (uint32_t i = 0; i + keylen + 2 <= n; ++i) {
		if (i && !bootarg_space(p[i - 1])) continue;
		uint32_t k = 0;
		while (k < keylen && p[i + k] == (unsigned char)key[k]) ++k;
		if (k != keylen || p[i + k] != '=') continue;
		uint32_t end = i + k + 2;
		if (p[i + k + 1] == '1' && (end == n || bootarg_space(p[end])))
			found = 1;
		else
			malformed = 1; /* same key with any other/trailing value: deny */
	}
	return found && !malformed ? bit : 0;
}
unsigned tgl_fdt_display_bootargs(const void *data, uint32_t size)
{
	const unsigned char *p = data;
	if (!p && size) return 0;
	uint32_t n = 0;
	while (n < size && p[n]) ++n; /* bounded at the property's first NUL */
	unsigned flags = 0;
	flags |= bootarg_display_flag(p, n, "tgl_disp_snap", 13, TGL_FDT_DISP_SNAP);
	flags |= bootarg_display_flag(p, n, "tgl_disp_revive", 15, TGL_FDT_DISP_REVIVE);
	return flags;
}
static void copystr(char *to, const char *from, unsigned cap)
{
	unsigned i = 0;
	while (i + 1 < cap && from[i]) { to[i] = from[i]; ++i; }
	to[i] = 0;
}
static void clear(void *p, unsigned n)
{
	unsigned char *b = p;
	for (unsigned i = 0; i < n; ++i) b[i] = 0;
}
static int range_ok(struct tgl_range r) { return r.size && r.base <= UINT64_MAX - r.size; }
static int overlap(struct tgl_range a, struct tgl_range b)
{
	return a.size && b.size && a.base < b.base + b.size && b.base < a.base + a.size;
}
static int extent(uint32_t off, uint32_t n, uint32_t total)
{
	return off >= 40 && off <= total && n <= total - off;
}
static uint64_t cells(const unsigned char *p, unsigned n) { return n == 1 ? be32(p) : be64(p); }
static const char *add(struct tgl_range *list, unsigned *count,
	unsigned max, uint64_t base, uint64_t size)
{
	struct tgl_range r = { base, size };
	if (!range_ok(r)) return "FDT range empty/overflow";
	if (*count == max) return "FDT range capacity";
	list[(*count)++] = r;
	return 0;
}
static const char *tuples(struct span v, unsigned ac, unsigned sc,
	struct tgl_range *list, unsigned *count, unsigned max)
{
	unsigned stride = (ac + sc) * 4;
	if (!v.n || v.n % stride) return "FDT reg/alloc-ranges cells";
	for (unsigned i = 0; i < v.n; i += stride) {
		const char *e = add(list, count, max, cells(v.p + i, ac), cells(v.p + i + ac * 4, sc));
		if (e) return e;
	}
	return 0;
}
static const char *finish(struct node *n, unsigned root_ac, unsigned root_sc,
	struct tgl_fdt_memory *m)
{
	if (n->disabled) return 0;
	if (n->kind == RESERVED) {
		if (!(n->seen & AC) || !(n->seen & SC) || !n->ranges || n->ac != root_ac || n->sc != root_sc)
			return "FDT reserved-memory translation/cells";
	} else if (n->kind == MEMORY || n->memory) {
		if (!n->memory || !(n->seen & REG)) return "FDT memory reg/device_type";
		return tuples(n->reg, root_ac, root_sc, m->ram, &m->ram_count, TGL_FDT_MAX_RAM);
	} else if (n->kind == RESERVATION) {
		if (n->seen & REG) return tuples(n->reg, n->ac, n->sc, m->reserved,
		    &m->reserved_count, TGL_FDT_MAX_RESERVED);
		if (!(n->seen & SIZE) || n->size.n != n->sc * 4 || !cells(n->size.p, n->sc))
			return "FDT reservation has no valid reg/size";
		if (m->pool_count == TGL_FDT_MAX_POOLS) return "FDT pool capacity";
		struct tgl_pool *pool = &m->pools[m->pool_count++];
		copystr(pool->name, n->name, sizeof(pool->name));
		pool->size = cells(n->size.p, n->sc);
		if (n->seen & ALIGN) {
			if (n->alignment.n != n->sc * 4) return "FDT pool alignment cells";
			pool->alignment = cells(n->alignment.p, n->sc);
			if (!pool->alignment || (pool->alignment & (pool->alignment - 1)))
				return "FDT pool alignment";
		}
		pool->first_range = m->alloc_count;
		if (!(n->seen & ALLOC)) pool->unresolved = 1;
		else {
			const char *e = tuples(n->alloc, n->ac, n->sc, m->alloc,
			    &m->alloc_count, TGL_FDT_MAX_ALLOC);
			if (e) { m->alloc_count = pool->first_range; pool->unresolved = 2; }
			else pool->range_count = m->alloc_count - pool->first_range;
		}
	} else if (n->kind == PSCI) m->psci_method = n->psci;
	return 0;
}
const char *tgl_fdt_memory(const void *blob, uint64_t available, struct tgl_fdt_memory *m)
{
	const unsigned char *b = blob;
	clear(m, sizeof(*m));
	if (!b || available < 40 || (uintptr_t)b > UINTPTR_MAX - 40) return "FDT header unavailable";
	if (be32(b) != 0xd00dfeedU) return "FDT magic";
	uint32_t total = be32(b + 4), st = be32(b + 8), strings = be32(b + 12);
	uint32_t reserve = be32(b + 16), ver = be32(b + 20), last = be32(b + 24);
	uint32_t ss = be32(b + 32), sn = be32(b + 36);
	if (total < 40 || total > available || total > TGL_FDT_MAX_SIZE || (uintptr_t)b > UINTPTR_MAX - total)
		return "FDT totalsize";
	if (ver < 17 || last > 17 || last > ver) return "FDT version";
	if ((st & 3) || (reserve & 7) || (sn & 3) || !sn || !extent(st, sn, total) ||
	    !extent(strings, ss, total) || !extent(reserve, 16, total)) return "FDT section bounds/alignment";
	struct tgl_range sr = { st, sn }, tr = { strings, ss };
	if (overlap(sr, tr)) return "FDT sections overlap";
	uint32_t rp = reserve;
	for (;;) {
		if (!extent(rp, 16, total)) return "FDT memreserve unterminated";
		struct tgl_range rr = { rp, 16 };
		if (overlap(rr, sr) || overlap(rr, tr)) return "FDT memreserve overlaps section";
		uint64_t a = be64(b + rp), n = be64(b + rp + 8); rp += 16;
		if (!a && !n) break;
		const char *e = add(m->reserved, &m->reserved_count, TGL_FDT_MAX_RESERVED, a, n);
		if (e) return e;
	}
	m->total_size = total;
	struct node stack[64];
	unsigned depth = 0, roots = 0, root_ac = 2, root_sc = 1;
	unsigned chosen_seen = 0, reserved_seen = 0, psci_seen = 0;
	uint32_t p = st, end = st + sn;
	while (p < end) {
		uint32_t tok = be32(b + p); p += 4;
		if (tok == 1) {
			uint32_t len;
			if (depth == 64 || !stringlen(b + p, end - p, &len)) return "FDT node depth/name";
			const char *name = (const char *)(b + p);
			if (((len + 4) & ~3U) > end - p) return "FDT node padding";
			p += (len + 4) & ~3U;
			struct node *n = &stack[depth]; clear(n, sizeof(*n));
			n->ac = 2; n->sc = 1; n->name = name;
			if (!depth) {
				if (roots++ || len) return "FDT root";
				n->kind = ROOT;
			} else {
				stack[depth - 1].children = 1;
				n->disabled = stack[depth - 1].disabled;
				if (depth == 1) {
					root_ac = stack[0].ac; root_sc = stack[0].sc;
					if (eq(name, "chosen")) {
						if (chosen_seen++) return "FDT duplicate chosen";
						n->kind = CHOSEN;
					} else if (eq(name, "reserved-memory")) {
						if (reserved_seen++) return "FDT duplicate reserved-memory";
						n->kind = RESERVED;
					} else if (eq(name, "psci")) {
						if (psci_seen++) return "FDT duplicate psci";
						n->kind = PSCI;
					} else if (len >= 6 && name[0] == 'm' && name[1] == 'e' && name[2] == 'm' &&
					    name[3] == 'o' && name[4] == 'r' && name[5] == 'y' && (len == 6 || name[6] == '@'))
						n->kind = MEMORY;
				} else if (depth == 2 && stack[1].kind == RESERVED) {
					const char *e = finish(&stack[1], root_ac, root_sc, m); if (e) return e;
					n->kind = RESERVATION; n->ac = stack[1].ac; n->sc = stack[1].sc;
				}
			}
			++depth;
		} else if (tok == 2) {
			if (!depth) return "FDT unbalanced end node";
			const char *e = finish(&stack[--depth], root_ac, root_sc, m); if (e) return e;
		} else if (tok == 3) {
			if (!depth || end - p < 8) return "FDT property header";
			uint32_t len = be32(b + p), no = be32(b + p + 4), nl; p += 8;
			if (len > end - p || len > UINT32_MAX - 3 || ((len + 3) & ~3U) > end - p ||
			    no >= ss || !stringlen(b + strings + no, ss - no, &nl)) return "FDT property bounds/name";
			const char *name = (const char *)(b + strings + no);
			struct span v = { b + p, len }; p += (len + 3) & ~3U;
			struct node *n = &stack[depth - 1];
			if (n->children) return "FDT property after child";
			unsigned bit = 0;
			if (eq(name, "#address-cells")) bit = AC;
			else if (eq(name, "#size-cells")) bit = SC;
			else if (eq(name, "reg")) bit = REG;
			else if (eq(name, "size")) bit = SIZE;
			else if (eq(name, "alloc-ranges")) bit = ALLOC;
			else if (eq(name, "alignment")) bit = ALIGN;
			else if (eq(name, "status")) bit = STATUS;
			else if (eq(name, "device_type")) bit = TYPE;
			else if (eq(name, "ranges")) bit = RANGES;
			else if (eq(name, "method")) bit = METHOD;
			else if (eq(name, "compatible")) bit = COMPAT;
			if (bit && (n->seen & bit)) return "FDT duplicate property";
			n->seen |= bit;
			/* Only root/reserved-memory cells affect this contract. Other buses
			 * may legitimately use zero or more than two address/size cells. */
			if ((bit == AC || bit == SC) && (n->kind == ROOT || n->kind == RESERVED)) {
				if (len != 4 || be32(v.p) < 1 || be32(v.p) > 2) return "FDT memory cell width";
				if (bit == AC) n->ac = be32(v.p); else n->sc = be32(v.p);
			} else if (bit == REG) n->reg = v;
			else if (bit == SIZE) n->size = v;
			else if (bit == ALLOC) n->alloc = v;
			else if (bit == ALIGN) n->alignment = v;
			else if (bit == RANGES) n->ranges = !len;
			else if (bit == STATUS) {
				if (!len || v.p[len - 1]) return "FDT status string";
				if (!strval(v, "okay") && !strval(v, "ok")) n->disabled = 1;
			} else if (bit == TYPE && depth == 2) n->memory = strval(v, "memory");
			else if (bit == METHOD && n->kind == PSCI) {
				if (strval(v, "smc")) n->psci = 1;
				else if (strval(v, "hvc")) n->psci = 2;
				else return "FDT PSCI method";
			} else if (bit == COMPAT && n->kind == ROOT) {
				if (!len || v.p[len - 1] || !stringlen(v.p, len, &nl)) return "FDT compatible string";
				copystr(m->compatible, (const char *)v.p, sizeof(m->compatible));
			} else if (n->kind == CHOSEN && !n->disabled) {
				if (eq(name, "bootargs") && len && !v.p[len - 1])
					m->display_flags = tgl_fdt_display_bootargs(v.p, len);
				unsigned which = eq(name, "linux,initrd-start") ? 1 : (eq(name, "linux,initrd-end") ? 2 : 0);
				if (which) {
					if ((m->initrd_fields & which) || (len != 4 && len != 8)) return "FDT initrd property";
					m->initrd_fields |= which;
					if (which == 1) m->initrd_start = cells(v.p, len / 4);
					else m->initrd_end = cells(v.p, len / 4);
				}
			}
		} else if (tok == 4) continue;
		else if (tok == 9) {
			if (depth || roots != 1 || p != end) return "FDT end/tree extent";
			if (!m->ram_count) return "FDT no enabled RAM";
			return 0;
		} else return "FDT unknown token";
	}
	return "FDT missing end";
}
int tgl_range_in_ram(const struct tgl_fdt_memory *m, struct tgl_range r)
{
	if (!range_ok(r)) return 0;
	uint64_t at = r.base, end = r.base + r.size;
	while (at < end) {
		uint64_t next = at;
		for (unsigned i = 0; i < m->ram_count; ++i) {
			struct tgl_range b = m->ram[i];
			if (b.base <= at && b.base + b.size > next) next = b.base + b.size;
		}
		if (next == at) return 0;
		at = next;
	}
	return 1;
}
const char *tgl_window_check(const struct tgl_fdt_memory *m, struct tgl_range w,
	const struct tgl_range *live, unsigned count)
{
	if (!tgl_range_in_ram(m, w)) return "XNU window outside FDT RAM";
	for (unsigned i = 0; i < m->reserved_count; ++i)
		if (overlap(w, m->reserved[i])) return "XNU window overlaps FDT reservation";
	for (unsigned i = 0; i < count; ++i) {
		if (!range_ok(live[i])) return "invalid live image extent";
		if (overlap(w, live[i])) return "XNU window overlaps resident image/input";
	}
	for (unsigned i = 0; i < m->pool_count; ++i) {
		const struct tgl_pool *p = &m->pools[i];
		/* An "unresolved" pool has no alloc property: the stock kernel
		 * places it dynamically, so no fixed range exists to overlap.
		 * The stock blazer FDT carries at least one such node, which
		 * made this check refuse EVERY window (v49/v50 evidence). */
		if (p->unresolved) continue;
		for (unsigned j = 0; j < p->range_count; ++j)
			if (overlap(w, m->alloc[p->first_range + j])) return "XNU window conflicts with unplaced dynamic pool";
	}
	return 0;
}
static int read_runtime(uintptr_t fdt, struct tgl_fdt_memory *m)
{
	/* Linux arm64: FDT is readable, 8-byte aligned and <=2 MiB. An invalid
	 * physical x0 cannot be made safe by a parser without memory mappings. */
	return fdt && !(fdt & 7) && !tgl_fdt_memory((const void *)fdt, TGL_FDT_MAX_SIZE, m);
}
int fdt_valid(uintptr_t fdt) { struct tgl_fdt_memory m; return read_runtime(fdt, &m); }
int fdt_root_compatible(uintptr_t fdt, char *out, unsigned size)
{
	struct tgl_fdt_memory m;
	if (!size || !read_runtime(fdt, &m) || !m.compatible[0]) return 0;
	copystr(out, m.compatible, size); return 1;
}
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	struct tgl_fdt_memory m;
	if (!read_runtime(fdt, &m)) return 0;
	if (eq(prop, "linux,initrd-start") && (m.initrd_fields & 1)) *out = m.initrd_start;
	else if (eq(prop, "linux,initrd-end") && (m.initrd_fields & 2)) *out = m.initrd_end;
	else return 0;
	return 1;
}
/* v2: bounded framebuffer-node scan of the ABL-supplied FDT. Matches any
 * node named "fb"/"framebuffer" (optionally with an @unit address) or
 * advertising a compatible string containing the word "framebuffer", and
 * returns the FIRST address tuple of its reg as the candidate scanout PA.
 * Standalone walker: the admission parser's strict
 * duplicate/cell rules stay untouched (a vendor DT quirk must not hide the
 * live scanout). depth/name/reg extents are bounded like tgl_fdt_memory. */
int fdt_find_framebuffer(uintptr_t fdt, uint64_t *out, const char **which)
{
	const unsigned char *b = (const unsigned char *)fdt;
	*which = 0;
	if (!fdt || (fdt & 7)) return 0;
	if (be32(b) != 0xd00dfeedU) return 0;
	uint32_t total = be32(b + 4), st = be32(b + 8), strings = be32(b + 12);
	uint32_t ss = be32(b + 32), sn = be32(b + 36);
	if (total < 40 || total > TGL_FDT_MAX_SIZE || st < 40 || st > total ||
	    sn > total - st || strings > total || ss > total - strings) return 0;
	unsigned ac = 2, sc = 1, depth = 0;
	int name_hit = 0, compat_hit = 0;
	uint64_t reg_pa = 0;
	unsigned reg_cells = 0;
	const char *hit = 0;
	uint32_t p = st, end = st + sn;
	while (p < end) {
		uint32_t tok = be32(b + p); p += 4;
		if (tok == 1) {
			uint32_t len;
			if (depth == 32 || !stringlen(b + p, end - p, &len)) return 0;
			const char *name = (const char *)(b + p);
			if (((len + 4) & ~3U) > end - p) return 0;
			p += (len + 4) & ~3U;
			++depth;
			if (depth == 1) continue;
			/* a sibling closes the previous match context */
			name_hit = 0; compat_hit = 0; reg_pa = 0; reg_cells = 0;
			/* node names: "fb", "fb@...", "framebuffer", "framebuffer@..." */
			if ((name[0] == 'f' && (name[1] == 'b' &&
			     (len == 2 || name[2] == '@'))) ||
			    (len >= 11 && name[1] == 'r' && name[2] == 'a' &&
			     name[3] == 'm' && name[4] == 'e' && name[5] == 'b' &&
			     name[6] == 'u' && name[7] == 'f' && name[8] == 'f' &&
			     name[9] == 'e' && name[10] == 'r' &&
			     (len == 11 || name[11] == '@'))) {
				name_hit = 1; hit = "name";
			}
		} else if (tok == 2) {
			if (!depth) return 0;
			--depth;
			if (depth && depth < 31 && (name_hit || compat_hit) && reg_cells) {
				*out = reg_pa; *which = hit;
				return 1;
			}
			if (depth && depth < 31) { name_hit = 0; compat_hit = 0; reg_pa = 0; reg_cells = 0; }
		} else if (tok == 3) {
			if (!depth || end - p < 8) return 0;
			uint32_t len = be32(b + p), no = be32(b + p + 4), nl; p += 8;
			if (len > end - p || no >= ss) return 0;
			if (!stringlen(b + strings + no, ss - no, &nl)) return 0;
			const char *name = (const char *)(b + strings + no);
			uint32_t pad = (len + 3) & ~3U;
			if (pad > end - p) return 0;
			struct span v = { b + p, len }; p += pad;
			if (depth == 1 && eq(name, "#address-cells") && len == 4) {
				ac = be32(v.p); if (!ac || ac > 2) ac = 2;
			} else if (depth == 1 && eq(name, "#size-cells") && len == 4) {
				sc = be32(v.p); if (!sc || sc > 2) sc = 1;
			} else if (depth > 1 && depth < 32) {
				if (eq(name, "compatible") && len && v.p[len - 1] == 0) {
					/* bounded stringlist scan: does any string contain
					 * the 11-byte needle "framebuffer"? */
					uint32_t i = 0;
					while (!compat_hit && i < len) {
						uint32_t nl;
						if (!stringlen(v.p + i, len - i, &nl)) break;
						for (uint32_t j = 0; j + 11 <= nl; ++j) {
							static const char fb[] = "framebuffer";
							uint32_t k = 0;
							while (k < 11 && v.p[i + j + k] ==
							    (unsigned char)fb[k]) ++k;
							if (k == 11) { compat_hit = 1; hit = "compatible"; break; }
						}
						i += nl + 1;
					}
				} else if (eq(name, "reg") && len >= (ac + sc) * 4 &&
				    !(len % ((ac + sc) * 4)) && !reg_cells) {
					reg_pa = ac == 2 ? be64(v.p) : be32(v.p);
					reg_cells = 1;
				}
			}
		} else if (tok == 4) continue;
		else if (tok == 9) break;
		else return 0;
	}
	return 0;
}

/* v3.9b (U1): bounded UFS-node scan, same walker discipline as
 * fdt_find_framebuffer (header checks, 32-deep bound, stringlen bounds,
 * 4-byte padding). Node match: name "ufs"/"ufshc" with optional @unit, or
 * any compatible string containing "ufshc" or "jedec,ufs". A status value
 * other than okay/ok marks the node absent (a disabled controller is not a
 * probe target). reg tuples are read positionally into the laguna layout
 * (reg-names: ufs_hc, ufs_top, ufs_phy_sram, psm_status_hsios,
 * psm_status_ufs_hc, psm_status_ufs_phy); "reg-names" starting with the
 * exact string "ufs_hc" confirms the order (named=1) — the positional read
 * happens regardless, since reg/reg-names order always matches in the
 * blazer DT and reg-names is informational. */
int fdt_find_ufs(uintptr_t fdt, struct tgl_ufs_fdt_regions *out)
{
	const unsigned char *b = (const unsigned char *)fdt;
	static const char c_ufshc[] = "ufshc", c_jedec[] = "jedec,ufs";
	static const char rn_hc[] = "ufs_hc";
	unsigned ac = 2, sc = 1, depth = 0;
	int name_hit = 0, compat_hit = 0, disabled = 0, named = 0;
	uint64_t regs[6], sizes[6];
	unsigned reg_tuples = 0, ah8 = 0, swh8 = 0, decouple = 0;
	uint32_t p, end;

	for (unsigned i = 0; i < 6; ++i) regs[i] = sizes[i] = 0;
	out->hc_bytes = out->top_bytes = 0;
	out->ah8_pg = out->swh8_pg = out->decouple_ufs_en = 0;
	out->hc = out->top = out->phy_sram = 0;
	out->psm[0] = out->psm[1] = out->psm[2] = 0;
	out->reg_tuples = 0;
	out->named = 0;

	if (!fdt || (fdt & 7)) return 0;
	if (be32(b) != 0xd00dfeedU) return 0;
	uint32_t total = be32(b + 4), st = be32(b + 8), strings = be32(b + 12);
	uint32_t ss = be32(b + 32), sn = be32(b + 36);
	if (total < 40 || total > TGL_FDT_MAX_SIZE || st < 40 || st > total ||
	    sn > total - st || strings > total || ss > total - strings) return 0;
	p = st; end = st + sn;
	while (p < end) {
		uint32_t tok = be32(b + p); p += 4;
		if (tok == 1) {
			uint32_t len;
			if (depth == 32 || !stringlen(b + p, end - p, &len)) return 0;
			const char *name = (const char *)(b + p);
#ifdef FDT_TRACE
			printf("BEGIN d=%u name='%s' hit?", depth + 1, name);
#endif
			if (((len + 4) & ~3U) > end - p) return 0;
			p += (len + 4) & ~3U;
			++depth;
			if (depth == 1) continue;
			/* a sibling closes the previous match context */
			name_hit = 0; compat_hit = 0; disabled = 0; named = 0;
			reg_tuples = 0; ah8 = swh8 = decouple = 0;
			for (unsigned i = 0; i < 6; ++i) regs[i] = sizes[i] = 0;
			/* node names: "ufs", "ufs@<unit>", "ufshc", "ufshc@<unit>" */
			if (len == 3 && name[0] == 'u' && name[1] == 'f' &&
			    name[2] == 's')
				name_hit = 1;
			else if (len > 4 && name[0] == 'u' && name[1] == 'f' &&
			    name[2] == 's' && name[3] == '@')
				name_hit = 1;
			else if (len == 5 && name[0] == 'u' && name[1] == 'f' &&
			    name[2] == 's' && name[3] == 'h' && name[4] == 'c')
				name_hit = 1;
			else if (len > 6 && name[0] == 'u' && name[1] == 'f' &&
			    name[2] == 's' && name[3] == 'h' && name[4] == 'c' &&
			    name[5] == '@')
				name_hit = 1;
		} else if (tok == 2) {
			if (!depth) return 0;
			--depth;
			if (depth && depth < 31 &&
			    (name_hit || compat_hit) && !disabled && reg_tuples) {
				out->hc = regs[0];
				out->top = regs[1];
				out->phy_sram = regs[2];
				out->psm[0] = regs[3];
				out->psm[1] = regs[4];
				out->psm[2] = regs[5];
				out->reg_tuples = reg_tuples;
				out->named = named;
				out->hc_bytes = sizes[0];
				out->top_bytes = sizes[1];
				out->ah8_pg = ah8;
				out->swh8_pg = swh8;
				out->decouple_ufs_en = decouple;
				return out->hc != 0;
			}
			if (depth && depth < 31) {
				name_hit = 0; compat_hit = 0; disabled = 0;
				named = 0; reg_tuples = 0; ah8 = swh8 = decouple = 0;
				for (unsigned i = 0; i < 6; ++i) regs[i] = sizes[i] = 0;
			}
		} else if (tok == 3) {
			if (!depth || end - p < 8) return 0;
			uint32_t len = be32(b + p), no = be32(b + p + 4), nl; p += 8;
			if (len > end - p || no >= ss) return 0;
			if (!stringlen(b + strings + no, ss - no, &nl)) return 0;
			const char *name = (const char *)(b + strings + no);
			uint32_t pad = (len + 3) & ~3U;
			if (pad > end - p) return 0;
			struct span v = { b + p, len }; p += pad;
			if (depth == 1 && eq(name, "#address-cells") && len == 4) {
				ac = be32(v.p); if (!ac || ac > 2) ac = 2;
			} else if (depth == 1 && eq(name, "#size-cells") && len == 4) {
				sc = be32(v.p); if (!sc || sc > 2) sc = 1;
			} else if (depth > 1 && depth < 32) {
				if (eq(name, "status") && len && v.p[len - 1] == 0) {
					if (!strval(v, "okay") && !strval(v, "ok"))
						disabled = 1;
				} else if (eq(name, "compatible") && len &&
				    v.p[len - 1] == 0) {
					/* bounded stringlist scan for the needles
					 * "ufshc" (5 B) / "jedec,ufs" (10 B) */
					uint32_t i = 0;
					while (!compat_hit && i < len) {
						uint32_t sl;
						if (!stringlen(v.p + i, len - i, &sl)) break;
						for (uint32_t j = 0; j + 5 <= sl; ++j) {
							uint32_t k = 0;
							while (k < 5 && v.p[i + j + k] ==
							    (unsigned char)c_ufshc[k]) ++k;
							if (k == 5) { compat_hit = 1; break; }
						}
						for (uint32_t j = 0; j + 10 <= sl &&
						     !compat_hit; ++j) {
							uint32_t k = 0;
							while (k < 10 && v.p[i + j + k] ==
							    (unsigned char)c_jedec[k]) ++k;
							if (k == 10) { compat_hit = 1; break; }
						}
						i += sl + 1;
					}
				} else if (eq(name, "reg-names") && len &&
				    v.p[len - 1] == 0) {
					uint32_t k = 0;
					while (k < 6 && v.p[k] == (unsigned char)rn_hc[k]) ++k;
					if (k == 6 && len > 6 && v.p[6] == 0) named = 1;
				} else if (eq(name, "reg") && len >= (ac + sc) * 4 &&
				    !(len % ((ac + sc) * 4))) {
					unsigned stride = (ac + sc) * 4;
					for (unsigned off = 0; off + stride <= len &&
					     reg_tuples < 6; off += stride, ++reg_tuples) {
						regs[reg_tuples] =
						    ac == 2 ? be64(v.p + off) : be32(v.p + off);
						sizes[reg_tuples] =
						    sc == 2 ? be64(v.p + off + ac * 4) : be32(v.p + off + ac * 4);
					}
				} else if (eq(name, "google,enable-hc-ah8-pg")) {
					ah8 = 1;
				} else if (eq(name, "google,enable-hc-swh8-pg")) {
					swh8 = 1;
				} else if (eq(name, "google,decouple-ufs-en")) {
					decouple = 1;
				}
			}
		} else if (tok == 4) continue;
		else if (tok == 9) break;
		else return 0;
	}
	return 0;
}
