// SPDX-License-Identifier: GPL-2.0+
/* Experimental RE-CP-02 TF installer. SPI/Factory are never written here. */
#ifdef JDTF_HOST_TEST
#include "jdtf-host-test.h"
#else
#include <common.h>
#include <mmc.h>
#include <blk.h>
#include <malloc.h>
#include <memalign.h>
#include <u-boot/crc.h>
#include <asm/unaligned.h>
#endif
#include "jdtf.h"

DECLARE_GLOBAL_DATA_PTR;

#define CHUNK (128 * 1024)
#define SECTORS(n) (((n) + 511U) / 512U)
#define KERNEL_ADDR 0x84000000U
#define INITRD_ADDR 0x88000000U

static int header_ok(struct jdtf_header *h)
{
	u32 saved = le32_to_cpu(h->header_crc), sum;
	u32 k = le32_to_cpu(h->kernel_size);
	u32 i = le32_to_cpu(h->initrd_size);
	u32 r = le32_to_cpu(h->rootfs_size);
	if (memcmp(h->magic, JDTF_MAGIC, 8) ||
	    memcmp(h->board, JDTF_BOARD, sizeof(JDTF_BOARD)) ||
	    k < 64 || k > 16 * 1024 * 1024 || i < 64 ||
	    i > 16 * 1024 * 1024 || !r || r > 64 * 1024 * 1024 ||
	    1 + SECTORS(k) + SECTORS(i) > JDTF_BOOT_SECTORS)
		return 0;
	h->header_crc = 0;
	sum = crc32(0, (void *)h, sizeof(*h));
	h->header_crc = cpu_to_le32(saved);
	return sum == saved;
}

static struct blk_desc *card(void)
{
	struct mmc *m;
	if (mmc_initialize(gd->bd))
		return NULL;
	m = find_mmc_device(0);
	if (!m || mmc_init(m))
		return NULL;
	return mmc_get_blk_desc(m);
}

static void partition(u8 *p, u32 start, u32 size)
{
	memset(p, 0, 16);
	p[1] = p[5] = 0xfe;
	p[2] = p[3] = p[6] = p[7] = 0xff;
	p[4] = 0x83;
	put_unaligned_le32(start, p + 8);
	put_unaligned_le32(size, p + 12);
}

static int known_layout(u8 *mbr, u32 sectors)
{
	return mbr[510] == 0x55 && mbr[511] == 0xaa &&
		get_unaligned_le32(mbr + 440) == JDTF_DISK_ID &&
		get_unaligned_le32(mbr + 454) == JDTF_BOOT_LBA &&
		get_unaligned_le32(mbr + 458) == JDTF_BOOT_SECTORS &&
		get_unaligned_le32(mbr + 470) == JDTF_ROOT_LBA &&
		get_unaligned_le32(mbr + 474) == JDTF_ROOT_SECTORS &&
		get_unaligned_le32(mbr + 486) == JDTF_OVERLAY_LBA &&
		get_unaligned_le32(mbr + 490) == sectors - JDTF_OVERLAY_LBA;
}

/* A bounded aligned bounce buffer also makes final partial blocks deterministic. */
static int write_verify(struct blk_desc *d, u32 lba, const void *src, u32 len)
{
	u8 *buf = memalign(ARCH_DMA_MINALIGN, CHUNK);
	u32 n, count, left = len, crc = 0;
	if (!buf)
		return -ENOMEM;
	while (left) {
		n = min(left, (u32)CHUNK);
		count = SECTORS(n);
		memset(buf, 0, count * 512);
		memcpy(buf, src, n);
		if (blk_dwrite(d, lba, count, buf) != count ||
		    blk_dread(d, lba, count, buf) != count)
			goto fail;
		crc = crc32(crc, buf, n);
		src += n;
		left -= n;
		lba += count;
	}
	free(buf);
	return crc == crc32(0, src - len, len) ? 0 : -EIO;
fail:
	free(buf);
	return -EIO;
}

int jdtf_install(const void *data, unsigned int size)
{
	struct jdtf_header h;
	struct blk_desc *d;
	ALLOC_CACHE_ALIGN_BUFFER(u8, mbr, 512);
	u32 k, i, r, ko = 512, io, ro, total;
	int preserve;
	if (size < sizeof(h))
		return 1;
	memcpy(&h, data, sizeof(h));
	if (!header_ok(&h))
		return 1;
	k = le32_to_cpu(h.kernel_size);
	i = le32_to_cpu(h.initrd_size);
	r = le32_to_cpu(h.rootfs_size);
	io = ko + SECTORS(k) * 512;
	ro = io + SECTORS(i) * 512;
	total = ro + SECTORS(r) * 512;
	if (total != size || crc32(0, data + ko, k) != le32_to_cpu(h.kernel_crc) ||
	    crc32(0, data + io, i) != le32_to_cpu(h.initrd_crc) ||
	    crc32(0, data + ro, r) != le32_to_cpu(h.rootfs_crc)) {
		printf("Invalid or truncated JDTF package\n");
		return 1;
	}
	d = card();
	if (!d || d->blksz != 512 || d->lba < 1048576 || d->lba > 0xffffffffU) {
		printf("TF installation requires a 512-byte-sector card >= 512 MiB\n");
		return 1;
	}
	if (blk_dread(d, 0, 1, mbr) != 1)
		return 1;
	preserve = known_layout(mbr, d->lba);
	printf("JDTF: %s TF overlay; SPI and Factory untouched\n",
		preserve ? "preserving" : "INITIALIZING (erases existing TF data)");
	memset(mbr, 0, 512);
	/* Invalidate TF boot before changing either component. */
	if (blk_dwrite(d, JDTF_BOOT_LBA, 1, mbr) != 1)
		return 1;
	if (!preserve) {
		put_unaligned_le32(JDTF_DISK_ID, mbr + 440);
		partition(mbr + 446, JDTF_BOOT_LBA, JDTF_BOOT_SECTORS);
		partition(mbr + 462, JDTF_ROOT_LBA, JDTF_ROOT_SECTORS);
		partition(mbr + 478, JDTF_OVERLAY_LBA, d->lba - JDTF_OVERLAY_LBA);
		mbr[510] = 0x55;
		mbr[511] = 0xaa;
		if (blk_dwrite(d, 0, 1, mbr) != 1)
			return 1;
		memset(mbr, 0, 512);
		memcpy(mbr, JDTF_EMPTY, sizeof(JDTF_EMPTY));
		if (blk_dwrite(d, JDTF_OVERLAY_LBA, 1, mbr) != 1)
			return 1;
	}
	if (write_verify(d, JDTF_ROOT_LBA, data + ro, r) ||
	    write_verify(d, JDTF_BOOT_LBA + 1, data + ko, SECTORS(k) * 512) ||
	    write_verify(d, JDTF_BOOT_LBA + 1 + SECTORS(k), data + io, SECTORS(i) * 512) ||
	    write_verify(d, JDTF_BOOT_LBA, &h, sizeof(h)))
		return 1;
	printf("JDTF install verified. Overlay initializes once on Linux first boot.\n");
	return 0;
}

int jdtf_boot(void)
{
	struct blk_desc *d = card();
	ALLOC_CACHE_ALIGN_BUFFER(struct jdtf_header, h, 1);
	u32 k, i;
	char cmd[80];
	if (!d || d->blksz != 512 || blk_dread(d, JDTF_BOOT_LBA, 1, h) != 1 ||
	    !header_ok(h))
		return 1;
	k = le32_to_cpu(h->kernel_size);
	i = le32_to_cpu(h->initrd_size);
	if (blk_dread(d, JDTF_BOOT_LBA + 1, SECTORS(k), (void *)KERNEL_ADDR) != SECTORS(k) ||
	    blk_dread(d, JDTF_BOOT_LBA + 1 + SECTORS(k), SECTORS(i), (void *)INITRD_ADDR) != SECTORS(i) ||
	    crc32(0, (void *)KERNEL_ADDR, k) != le32_to_cpu(h->kernel_crc) ||
	    crc32(0, (void *)INITRD_ADDR, i) != le32_to_cpu(h->initrd_crc))
		return 1;
	env_set("initrd_high", "ffffffff");
	env_set("bootargs", "console=ttyS0,115200n8 rdinit=/init");
	snprintf(cmd, sizeof(cmd), "bootm %x %x", KERNEL_ADDR, INITRD_ADDR);
	return run_command(cmd, 0);
}
