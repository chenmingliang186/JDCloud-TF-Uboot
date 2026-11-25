/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __JDTF_H
#define __JDTF_H
#define JDTF_MAGIC "JDTFv1\0"
#define JDTF_BOARD "jdcloud,re-cp-02"
#define JDTF_BOOT_LBA 2048U
#define JDTF_BOOT_SECTORS 65536U
#define JDTF_ROOT_LBA (JDTF_BOOT_LBA + JDTF_BOOT_SECTORS)
#define JDTF_ROOT_SECTORS 262144U
#define JDTF_OVERLAY_LBA (JDTF_ROOT_LBA + JDTF_ROOT_SECTORS)
#define JDTF_DISK_ID 0x4644544aU
#define JDTF_EMPTY "JDTF-EMPTY-v1"
struct jdtf_header {
	unsigned char magic[8];
	__le32 header_crc, kernel_size, initrd_size, rootfs_size;
	__le32 kernel_crc, initrd_crc, rootfs_crc;
	char board[32];
	unsigned char reserved[444];
} __packed;
int jdtf_install(const void *data, unsigned int size);
int jdtf_boot(void);
#endif
