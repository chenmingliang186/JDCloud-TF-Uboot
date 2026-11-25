#!/usr/bin/env python3
"""Convert an RE-CP-02 KWRT legacy sysupgrade image to a JDTF TF package.

Requires squashfs-tools, readelf, and the MIPS cross compiler. Does not access
physical disks. Output is for the companion JDTF-enabled U-Boot, not SPI mtd.
"""
import argparse
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib

BOARD = b"jdcloud,re-cp-02"
MAGIC = b"JDTFv1\0\0"
BOOT, ROOT, OVERLAY = 2048, 67584, 329728
REPO = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def pad(data, align=512):
    return data + bytes(-len(data) % align)


def uimage(data, kind=2, compression=3, load=0x80001000, entry=0x80001000, name=b"JDTF KWRT"):
    h = struct.pack(">7I4B32s", 0x27051956, 0, 0, len(data), load, entry,
                    zlib.crc32(data), 5, 5, kind, compression, name[:32])
    return h[:4] + struct.pack(">I", zlib.crc32(h)) + h[8:] + data


def parse_uimage(data, expected_type=2):
    if len(data) < 64:
        raise ValueError("Truncated uImage")
    h = struct.unpack(">7I4B32s", data[:64])
    if h[0] != 0x27051956 or h[8] != 5 or h[9] != expected_type:
        raise ValueError("Expected a MIPS legacy uImage")
    if zlib.crc32(data[:4] + bytes(4) + data[8:64]) != h[1]:
        raise ValueError("uImage header CRC mismatch")
    body = data[64:64+h[3]]
    if len(body) != h[3] or zlib.crc32(body) != h[6]:
        raise ValueError("uImage data CRC mismatch")
    return h, body


def patch_dtb(dtb, initrd_size):
    """Preserve the original tree; replace only /chosen initrd/boot arguments."""
    words = struct.unpack(">10I", dtb[:40])
    _, total, so, stro, reserve, version, last, cpuid, strslen, slen = words
    if total != len(dtb) or version < 16:
        raise ValueError("Invalid appended FDT")
    strings = bytearray(dtb[stro:stro+strslen])
    updates = {
        b"bootargs": b"console=ttyS0,115200n8 rdinit=/init\0",
        b"linux,initrd-start": struct.pack(">I", 0x08000040),
        b"linux,initrd-end": struct.pack(">I", 0x08000040 + initrd_size),
    }
    offsets = {}
    for name in updates:
        pos = strings.find(name+b"\0")
        if pos < 0:
            pos = len(strings)
            strings += name+b"\0"
        offsets[name] = pos
    out = bytearray()
    pos, path, found = so, [], False
    while pos < so+slen:
        start = pos
        token = struct.unpack_from(">I", dtb, pos)[0]
        pos += 4
        if token == 1:
            end = dtb.index(0, pos)
            path.append(dtb[pos:end])
            pos = (end+4) & ~3
        elif token == 2:
            if path == [b"", b"chosen"]:
                found = True
                for name, value in updates.items():
                    out += struct.pack(">3I", 3, len(value), offsets[name]) + pad(value, 4)
            path.pop()
        elif token == 3:
            length, nameoff = struct.unpack_from(">2I", dtb, pos)
            pos += 8
            name = dtb[stro+nameoff:dtb.index(0, stro+nameoff)]
            pos += (length+3) & ~3
            if path == [b"", b"chosen"] and name in updates:
                continue
        elif token == 9:
            out += dtb[start:pos]
            break
        elif token != 4:
            raise ValueError("Invalid FDT token")
        out += dtb[start:pos]
    if not found:
        raise ValueError("Original firmware has no /chosen")
    # Keep the original reservation map and its header offset intact.
    prefix = dtb[40:so]
    newso = 40+len(prefix)
    newstro = newso+len(out)
    h = struct.pack(">10I", 0xd00dfeed, newstro+len(strings), newso,
                    newstro, reserve, version, last, cpuid, len(strings), len(out))
    return h+prefix+out+strings


def patch_kernel(original, initrd_size):
    h, payload = parse_uimage(original)
    if h[10] != 3:
        raise ValueError("Only LZMA KWRT kernels are supported")
    raw = lzma.decompress(payload)
    if b"Unpacking initramfs" not in raw:
        raise ValueError("Kernel external initramfs support could not be confirmed")
    found = None
    pos = 0
    while True:
        pos = raw.find(b"\xd0\x0d\xfe\xed", pos)
        if pos < 0:
            break
        if pos+40 <= len(raw):
            size = struct.unpack_from(">I", raw, pos+4)[0]
            if size > 1000 and pos+size == len(raw):
                found = pos
        pos += 4
    if found is None or BOARD+b"\0" not in raw[found:]:
        raise ValueError("Expected an appended RE-CP-02 device tree")
    raw = raw[:found] + patch_dtb(raw[found:], initrd_size)
    return uimage(lzma.compress(raw, format=lzma.FORMAT_ALONE),
                  load=h[4], entry=h[5], name=b"JDTF RE-CP-02 KWRT")


def newc(tree):
    archive = bytearray()
    inode = 1

    def entry(name, mode, data=b"", major=0, minor=0):
        nonlocal inode
        name = name.encode()+b"\0"
        values = [inode, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(name), 0]
        archive.extend(b"070701" + b"".join(f"{v:08x}".encode() for v in values))
        archive.extend(name)
        archive.extend(bytes(-len(archive) % 4))
        archive.extend(data)
        archive.extend(bytes(-len(archive) % 4))
        inode += 1

    for p in sorted(tree.rglob("*")):
        name = str(p.relative_to(tree))
        mode = p.lstat().st_mode
        if p.is_symlink():
            entry(name, stat.S_IFLNK | 0o777, os.readlink(p).encode())
        elif p.is_dir():
            entry(name, stat.S_IFDIR | 0o755)
        else:
            entry(name, stat.S_IFREG | stat.S_IMODE(mode), p.read_bytes())
    entry("dev/console", stat.S_IFCHR | 0o600, major=5, minor=1)
    entry("dev/null", stat.S_IFCHR | 0o666, major=1, minor=3)
    entry("TRAILER!!!", 0)
    return pad(bytes(archive))


def make_initramfs(root, dest):
    for directory in ["bin", "sbin", "usr/sbin", "usr/lib", "lib", "dev", "proc", "sys", "tmp", "etc", "modules"]:
        (dest/directory).mkdir(parents=True, exist_ok=True)
    copied = set()

    def copy_elf(relative):
        relative = PurePosixPath(os.path.normpath("/"+str(relative))).relative_to("/")
        if str(relative) in copied:
            return
        copied.add(str(relative))
        src, dst = root/relative, dest/relative
        if not src.exists():
            # Absolute symlinks need resolving inside the extracted firmware tree.
            if not src.is_symlink():
                raise ValueError(f"Missing initramfs dependency: {relative}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            target = os.readlink(src)
            dst.symlink_to(target)
            nextpath = target.lstrip("/") if target.startswith("/") else str(relative.parent/target)
            copy_elf(nextpath)
            return
        shutil.copy2(src, dst)
        if src.read_bytes()[:4] != b"\x7fELF":
            return
        metadata = subprocess.check_output(["readelf", "-d", str(src)], text=True)
        for lib in re.findall(r"Shared library: \[([^]]+)\]", metadata):
            for folder in ["lib", "usr/lib"]:
                candidate = root/folder/lib
                if candidate.exists() or candidate.is_symlink():
                    copy_elf(folder+"/"+lib)
                    break
            else:
                raise ValueError(f"Missing shared library {lib}")

    for relative in ["bin/busybox", "sbin/insmod", "sbin/switch_root", "usr/sbin/mke2fs", "lib/ld-musl-mipsel-sf.so.1"]:
        copy_elf(relative)
    for applet in ["sh", "mount", "mkdir", "sleep", "dd", "grep", "sync", "cat", "cp", "rm"]:
        (dest/"bin"/applet).symlink_to("busybox")
    if (root/"etc/mke2fs.conf").exists():
        shutil.copy2(root/"etc/mke2fs.conf", dest/"etc/mke2fs.conf")
    modules = {p.stem.replace("-", "_"): p for p in (root/"lib/modules").rglob("*.ko")}
    loaded, loading, order = set(), set(), []

    def module(name):
        name = name.replace("-", "_")
        if name in loaded:
            return
        if name in loading or name not in modules:
            raise ValueError(f"Missing/cyclic module {name}")
        loading.add(name)
        p = modules[name]
        deps = re.search(rb"(?:^|\0)depends=([^\0]*)", p.read_bytes())
        if deps:
            for dep in deps[1].decode().split(","):
                if dep:
                    module(dep)
        target = dest/"modules"/p.name
        shutil.copy2(p, target)
        order.append("/modules/"+p.name)
        loaded.add(name)
        loading.remove(name)

    for name in ["mmc_block", "mtk-sd", "ext4"]:
        module(name)
    (dest/"modules.load").write_text("\n".join(order)+"\n")
    shutil.copy2(REPO/"tf/init", dest/"init")
    shutil.copy2(REPO/"tf/overlay.sh", dest/"overlay.sh")
    (dest/"init").chmod(0o755)
    return gzip.compress(newc(dest), mtime=0), order


def package(kernel, initrd, rootfs, generation=None):
    if not (64 <= len(kernel) <= 16*1024*1024 and 64 <= len(initrd) <= 16*1024*1024 and
            0 < len(rootfs) <= 64*1024*1024 and 512+len(pad(kernel))+len(pad(initrd)) <= 32*1024*1024):
        raise ValueError("JDTF size limits exceeded")
    header = bytearray(512)
    header[:8] = MAGIC
    struct.pack_into("<6I", header, 12, len(kernel), len(initrd), len(rootfs),
                     zlib.crc32(kernel), zlib.crc32(initrd), zlib.crc32(rootfs))
    header[36:36+len(BOARD)] = BOARD
    generation = generation or hashlib.sha256(kernel+initrd+rootfs).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", generation):
        raise ValueError("Invalid generation identifier")
    header[68:132] = generation.encode()
    struct.pack_into("<I", header, 8, zlib.crc32(header))
    return bytes(header)+pad(kernel)+pad(initrd)+pad(rootfs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("firmware", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--cc", required=True, help="MIPS musl cross compiler")
    ap.add_argument("--unsquashfs", default="unsquashfs")
    ap.add_argument("--mksquashfs", default="mksquashfs")
    ap.add_argument("--work", type=Path)
    args = ap.parse_args()
    original = args.firmware.read_bytes()
    h, payload = parse_uimage(original)
    squashoff = 64+h[3]
    if original[squashoff:squashoff+4] != b"hsqs":
        raise ValueError("Expected squashfs immediately after the legacy kernel")
    work = args.work or Path(tempfile.mkdtemp(prefix="jdtf-"))
    work.mkdir(parents=True, exist_ok=True)
    root = work/"root"
    if root.exists():
        raise ValueError("Use an empty work directory")
    run(args.unsquashfs, "-no-exit-code", "-d", root, "-o", squashoff, args.firmware)
    helper = work/"jdtf-image"
    run(args.cc, "-Os", "-static", "-s", "-o", helper, REPO/"tools/jdtf-image.c")
    shutil.copy2(helper, root/"sbin/jdtf-image")
    (root/"sbin/jdtf-image").chmod(0o755)
    shutil.move(root/"sbin/mount_root", root/"sbin/mount_root.mtd")
    for src, target in [("tf/mount_root", "sbin/mount_root"), ("tf/platform.sh", "lib/upgrade/platform.sh")]:
        shutil.copy2(REPO/src, root/target)
        (root/target).chmod(0o755)
    (root/"etc/jdtf-root").write_text("JDTF v1: jdcloud,re-cp-02\n")
    fingerprint = hashlib.sha256(original)
    for name in ["tools/build_jdtf.py", "tools/jdtf-image.c", "tf/init", "tf/overlay.sh", "tf/platform.sh", "tf/mount_root"]:
        fingerprint.update((REPO/name).read_bytes())
    generation = fingerprint.hexdigest()
    (root/"etc/jdtf-generation").write_text(generation+"\n")
    initrd, order = make_initramfs(root, work/"initramfs")
    ramdisk = uimage(initrd, kind=3, compression=1, load=0x88000040, entry=0,
                     name=b"JDTF matching initramfs")
    kernel = patch_kernel(original, len(initrd))
    rootfile = work/"rootfs.squashfs"
    run(args.mksquashfs, root, rootfile, "-noappend", "-all-root", "-comp", "xz", "-b", "262144", "-processors", "2")
    bundle = package(kernel, ramdisk, rootfile.read_bytes(), generation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bundle)
    report = {"source_sha256": hashlib.sha256(original).hexdigest(), "source": args.firmware.name,
              "output": args.output.name, "output_sha256": hashlib.sha256(bundle).hexdigest(),
              "size_bytes": len(bundle), "kernel_bytes": len(kernel), "initrd_bytes": len(ramdisk),
              "rootfs_bytes": rootfile.stat().st_size, "modules": order, "hardware_tested": False,
              "generation": generation,
              "layout": {"boot_lba": BOOT, "root_lba": ROOT, "overlay_lba": OVERLAY}}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
