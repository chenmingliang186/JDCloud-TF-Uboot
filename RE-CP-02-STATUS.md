# JDCloud RE-CP-02: integrated experimental TF installation

**All hardware behavior is UNTESTED.** This branch implements the software path
for TF installation and upgrading. It is not evidence of a successful hardware
boot or verified electrical/DDR compatibility.

## Deliverables and supported image format

- U-Boot still resides in SPI, within the 256 KiB U-Boot partition.
- The new U-Boot accepts a converted `*.jdtf.bin` KWRT TF package through its
  existing web recovery page. The supplied KWRT image has already been converted.
- An ordinary, unconverted KWRT sysupgrade BIN uploaded to U-Boot still goes to
  SPI; it does **not** automatically become a TF-installed image.
- Future KWRT releases must be converted with `tools/build_jdtf.py` before TF
  installation or LuCI/sysupgrade. No force override is required for valid JDTF.
- The converter supports this RE-CP-02 LZMA legacy-uImage + appended-DTB +
  squashfs family, with matching MMC/ext4 modules and mke2fs in the input image.
  Other formats are rejected instead of guessing compatibility.

## First installation and storage

Uploading JDTF to the web recovery page validates its sizes, board tag and CRCs
before writing the TF card. First installation **erases the existing TF layout**.
Only MMC device 0 is supported. Use a card >= 512 MiB with 512-byte sectors.

| TF partition | Start sector | Size | Use |
| --- | --- | --- | --- |
| p1 | 2048 | 32 MiB | package header, kernel and matching initramfs |
| p2 | 67584 | 128 MiB | read-only KWRT squashfs |
| p3 | 329728 | remaining card | ext4 overlay and persistent data |

The first Linux boot loads the matching MMC/ext4 modules from the external
initramfs. It formats p3 only when the explicit `JDTF-EMPTY-v1` marker is present,
mounts the rootfs and overlay, then starts the original KWRT init system.
A damaged existing overlay without the empty marker is never automatically
reformatted. `/` uses p3 for writable internal storage; `/overlay/data` is a
persistent data directory.

Normal boot attempts raw JDTF first, then the earlier FAT `/boot/uImage` path,
then SPI. Invalid headers/kernel/initramfs return to the SPI path. A hang after
entering Linux requires the existing reset-button web/TFTP recovery path.

## Upgrade behavior

- Web JDTF upgrade preserves p3. At next boot, configuration under `/etc` and
  user files under `/root` migrate; old installed software/modules do not carry
  across kernel versions. `/overlay/data` remains intact.
- LuCI/sysupgrade accepts a converted JDTF package. It runs from RAM, verifies the
  exact card layout before touching the overlay, restores the standard selected
  sysupgrade configuration backup, and writes only the TF kernel/rootfs regions.
- `sysupgrade -n` starts a fresh software overlay but retains `/overlay/data`.
- TF boot is invalidated before component writes; the new boot header is
  committed only after read-back verification. This allows SPI fallback after
  an interrupted write. Actual power-loss behavior has not been tested.
- CRC detects corruption, not a malicious signer. This is not secure boot.

## SPI and Factory

The TF installer/upgrader has no SPI/MTD write operations. The original kernel
DTS is retained except `/chosen` bootargs and external-initrd addresses, so
Factory calibration continues to be read from the original SPI partition.
Existing web/TFTP rescue code is retained. Ordinary SPI firmware upload bounds
remain checked separately.

| SPI region | Start | Length |
| --- | --- | --- |
| U-Boot | 0x000000 | 0x040000 |
| Config | 0x040000 | 0x010000 |
| Factory | 0x050000 | 0x040000 |
| firmware | 0x090000 | 0xF70000 |

GPIOs/partition map are based on the OpenWrt RE-CP-02 DTS:
https://github.com/openwrt/openwrt/blob/main/target/linux/ramips/dts/mt7621_jdcloud_re-cp-02.dts

Reset GPIO 18, blue LED GPIO 7, UART 115200, CPU 880 MHz. The existing build uses
**DDR3 256 MiB / 1200 MT/s as an unverified assumption**. Confirm the physical
board's DDR type/capacity/timing before flashing. No bootloader was flashed here.

## Building and converting

Build U-Boot using the pinned toolchain beside this repository:

```sh
bash build-re-cp-02.sh
```

Convert the next matching RE-CP-02 KWRT sysupgrade image on a Linux computer:

```sh
python3 tools/build_jdtf.py ORIGINAL-KWRT-sysupgrade.bin \
  --cc /path/to/mipsel-openwrt-linux-gcc \
  --output KWRT-RE-CP-02.jdtf.bin
```

Host prerequisites: Python 3, squashfs-tools, binutils/readelf, GCC, bison, flex,
bc, zlib/OpenSSL development headers. The converter never accesses a physical
disk. Matching modules, executable dependencies and initramfs are taken from
that exact input firmware.

Only `archive/u-boot-mt7621.bin` is the packed SPI bootloader. The larger
`u-boot.img` is an intermediate and must not be used as a 256 KiB replacement.
Never write the JDTF package to the SPI U-Boot/Factory/firmware partitions.

## Validation and remaining hardware tests

Local cross-compilation, final BIN size gates, image CRC/layout/decompression
checks, host tests of the actual U-Boot installer with sparse card files, Linux
writer tests, interrupted-write and overlay-migration tests were performed.
QEMU user-mode ran the MIPS package verifier, shell syntax checks and mke2fs on
a regular test file. User-mode execution is **not** whole-router emulation.

Unverified: DDR initialization, MMC pinmux/electrical operation, physical card
writes, reset/LED/Ethernet behavior, web upload on the router, external-initrd
handoff, complete Linux boot, Wi-Fi calibration, real LuCI upgrades and real
power-loss recovery. These must not be reported as hardware-verified features.
