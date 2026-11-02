/*
 * blazer_ufs_fullcheck=1: read every block of the root partition once and log CRC32s, for comparison with the image
 * on the host (tools/fullcheck.py). Reads only. Included by the kernel driver and by the host test.
 * The includer defines FC_READ(lba, count, out), FC_LOG(...), FC_NOW_MS(). If it defines FC_MASK_RUN(lba, count, &skip) too,
 * blocks that reports as skipped are neither read nor hashed, though they still count in the span's size: the persist table's
 * blocks, which a kernel may have written. The host's list must be computed with the same mask, and FC_MASK_LINE() says so.
 */
#define UFS_FC_BLOCK       4096u
#define UFS_FC_SPAN_BLOCKS 16384u /* 64 MiB */
#define UFS_FC_CHUNK       16u    /* the multi-block size blazer-ufs-test proved on the phone */

static uint32_t ufs_fc_table[256];

static void
ufs_fc_table_init(void)
{
	for (uint32_t i = 0; i < 256; i++) {
		uint32_t c = i;

		for (unsigned k = 0; k < 8; k++) {
			c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
		}
		ufs_fc_table[i] = c;
	}
}

/* 0 when every block was read. The first read error logs its partition LBA and stops the pass. */
static int
ufs_fc_run(uint64_t first_block, uint64_t nblocks)
{
	uint32_t whole = 0xffffffffu, span = 0xffffffffu, span_blocks = 0, spans = 0;
	uint64_t t0 = FC_NOW_MS();

	ufs_fc_table_init();
#ifdef FC_MASK_LINE
	FC_MASK_LINE();
#endif
	FC_LOG("blazer-ufs-fullcheck: start, %llu blocks at %llu, span %u\n", (unsigned long long)nblocks,
	    (unsigned long long)first_block, UFS_FC_SPAN_BLOCKS);
	for (uint64_t lba = 0; lba < nblocks;) {
		uint32_t count = UFS_FC_CHUNK;
		const uint8_t *d = NULL;
		int fc_skip = 0;
		int error;

		if (nblocks - lba < count) {
			count = (uint32_t)(nblocks - lba);
		}
		if (UFS_FC_SPAN_BLOCKS - span_blocks < count) {
			count = UFS_FC_SPAN_BLOCKS - span_blocks;
		}
#ifdef FC_MASK_RUN
		count = FC_MASK_RUN(lba, count, &fc_skip);
#endif
		if (!fc_skip) {
			error = FC_READ(first_block + lba, count, &d);
			if (error != 0) {
				FC_LOG("blazer-ufs-fullcheck: read error lba %llu count %u error %d, stopping\n",
				    (unsigned long long)lba, count, error);
				return 1;
			}
			for (uint32_t i = 0; i < count * UFS_FC_BLOCK; i++) {
				whole = (whole >> 8) ^ ufs_fc_table[(whole ^ d[i]) & 0xff];
				span = (span >> 8) ^ ufs_fc_table[(span ^ d[i]) & 0xff];
			}
			FC_DONE_READ();
		}
		lba += count;
		span_blocks += count;
		if (span_blocks == UFS_FC_SPAN_BLOCKS || lba == nblocks) {
			FC_LOG("blazer-ufs-fullcheck: span %u first %llu blocks %u crc %08x\n", spans,
			    (unsigned long long)(lba - span_blocks), span_blocks, ~span);
			spans++;
			span = 0xffffffffu;
			span_blocks = 0;
		}
	}
	FC_LOG("blazer-ufs-fullcheck: done, spans %u blocks %llu whole crc %08x, %llu ms\n", spans,
	    (unsigned long long)nblocks, ~whole, (unsigned long long)(FC_NOW_MS() - t0));
	return 0;
}
