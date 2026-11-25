# JDCloud RE-CP-02 bring-up status

This is a **partial implementation**, not a finished TF installer. All hardware
behavior is UNTESTED. No image has been flashed by this work.

## Delivered

- Local cross-compilation of the SPI baseline and experimental TF variant.
- Python 3 MT7621 packer replaces the old Python 2 binman/pylibfdt path for
  MT7621 only. Layout remains SPL, 0xff alignment padding, LZMA U-Boot payload.
- CI dependencies, fixed toolchain SHA-256, fail-fast builds, quoted workflow
  inputs, repeatable GPIO generation, and a 262144-byte final BIN size gate.
- Dedicated board build and CI matrix; CI has **not** been run on GitHub.
- Experimental SD/MMC pinmux and driver, FAT partition parsing, and
  `/boot/uImage` loading from MMC 0:1 before the existing SPI boot path.
- Existing reset-button web recovery and TFTP initramfs recovery code retained.
- TF variant SPI firmware writes enforce the fixed RE-CP-02 firmware region;
  uploads require a complete MIPS legacy uImage with valid header/data CRC.
  CRC is an integrity check, not signature or board-model authentication.

## Board assumptions

Partition map and GPIOs are based on OpenWrt's RE-CP-02 DTS:
https://github.com/openwrt/openwrt/blob/main/target/linux/ramips/dts/mt7621_jdcloud_re-cp-02.dts

| Region | Start | Length |
| --- | --- | --- |
| U-Boot | 0x000000 | 0x040000 |
| Config | 0x040000 | 0x010000 |
| Factory | 0x050000 | 0x040000 |
| firmware | 0x090000 | 0xF70000 |

Reset GPIO 18; blue status LED GPIO 7; serial 115200; CPU 880 MHz.
**DDR3 256 MiB / 1200 MT/s is an unverified build assumption** and must match
this physical board before any flashing. The 256 KiB limit alone does not
establish safe hardware compatibility.

## Feature matrix

| Requested function | Current result |
| --- | --- |
| Fix current Actions error | Build changes prepared; original log confirms python: not found in pylibfdt; remote rerun pending |
| Baseline build | Local build completed; BIN supplied |
| TF startup | Experimental FAT /boot/uImage loader compiled; requires a suitable kernel/rootfs; no hardware test |
| Web upload KWRT | Existing SPI upload retained, TF variant adds integrity/bounds checks; user's KWRT BIN not tested |
| Format TF as internal storage | **Not implemented** |
| Install an ordinary KWRT sysupgrade BIN onto TF | **Not implemented** |
| Subsequent TF firmware upgrades | **Not implemented** |
| Rescue and Factory preservation | Existing rescue paths retained; firmware-write bounds checked in TF source; hardware untested |
| U-Boot <= 256 KiB | Final BIN size checked locally |

## Important scope of TF startup

U-Boot itself still boots from SPI flash. It then attempts to load the Linux
kernel from TF. This is not MT7621 BootROM booting U-Boot directly from TF.

The FAT loader does not alter or format a TF card. A matching initramfs uImage
can be used for initial bring-up. A regular KWRT sysupgrade BIN copied to
`/boot/uImage` is not a complete TF-installed system: its rootfs placement,
MMC kernel driver, command line, overlay mount and sysupgrade logic must agree.
The 32 MiB load cap and `iminfo` check prevent booting a truncated large uImage.
If TF probing/loading/checking returns an error, the original SPI path runs.
A kernel that hangs after bootm cannot be recovered by that software fallback.

## Remaining implementation for the requested complete product

A matching KWRT build must supply an MMC-capable installer/initramfs, a defined
TF partition layout, rootfs/overlay mounting, and a sysupgrade platform handler.
Automatic formatting must occur in that installer, with a one-time marker and
explicit card selection, rather than on every normal boot. Upgrade image
validation must identify this board/layout before changing storage. Existing
Factory calibration data must continue to be read from SPI at 0x50000.
None of that Linux integration is included in these BINs.

## Build

Extract the pinned OpenWrt toolchain beside this repository, as in the workflows.
Install make, GCC, bison, flex, bc, OpenSSL development headers and Python 3.

Baseline:

```sh
./customize.sh NOR '256k(u-boot),64k(u-boot-env),256k(factory),-(firmware)' \
  0x90000 18 7 880 1200 DDR3-256MiB 115200
```

Experimental TF:

```sh
./build-re-cp-02.sh
```

Only `archive/u-boot-mt7621.bin` is the packed flash image. The much larger
`u-boot.img` is an intermediate, not a 256 KiB flash replacement.

Recovery code is unchanged: PC 192.168.1.2/24, router 192.168.1.1. Hold Reset
while powering on, release after 1–6 seconds of blinking for web recovery;
hold through 6 seconds for TFTP `recovery.bin` initramfs recovery. These timing,
Ethernet, GPIO and DDR assumptions have not been verified on this hardware.
Do not use these instructions as evidence that flashing has been validated.

## Repository access

Source was cloned from main commit 636b6e7c0db8a7bf0c5becfbc0e3660be6736ba3.
Browser login is available; GitHub CLI is not authenticated.
Changes are being uploaded through GitHub on a dedicated fix branch.
See the final delivery for remote build results.
