import ctypes
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("jdtf_builder", REPO/"tools/build_jdtf.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class InstallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        cls.libpath = cls.work/"install.so"
        subprocess.run(["gcc", "-shared", "-fPIC", "-O2", "-DJDTF_HOST_TEST",
                        "-iquote", str(REPO/"tests/host"), "-iquote", str(REPO/"include"),
                        str(REPO/"board/ralink/mt7621_rfb/jdtf.c"), "-lz", "-o", str(cls.libpath)], check=True)
        cls.lib = ctypes.CDLL(str(cls.libpath))
        cls.lib.jdtf_install.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        cls.tool = cls.work/"jdtf-image"
        subprocess.run(["gcc", "-Wall", "-Wextra", "-Werror", "-O2", "-DJDTF_TEST_FILES",
                        str(REPO/"tools/jdtf-image.c"), "-o", str(cls.tool)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.disk = self.work/"card.img"
        with self.disk.open("wb") as f:
            f.truncate(512*1024*1024)
            f.seek(512)
            f.write(b"reserved-before-partition")
        self.assertEqual(self.lib.jdtf_test_open(str(self.disk).encode()), 0)
        self.kernel = builder.uimage(b"kernel-test")
        self.initrd = builder.uimage(b"initrd-test", kind=3)
        self.rootfs = b"hsqs"+b"test-rootfs"*100
        self.image = builder.package(self.kernel, self.initrd, self.rootfs)

    def tearDown(self):
        self.lib.jdtf_test_close()

    def install(self, image=None):
        image = image if image is not None else self.image
        data = ctypes.create_string_buffer(image)
        return self.lib.jdtf_install(data, len(image))

    def read(self, off, size):
        with self.disk.open("rb") as f:
            f.seek(off)
            return f.read(size)

    def test_first_install_layout_readback_and_reserved_area(self):
        self.assertEqual(self.install(), 0)
        mbr = self.read(0, 512)
        self.assertEqual(mbr[510:], b"\x55\xaa")
        self.assertEqual(struct.unpack_from("<2I", mbr, 454), (builder.BOOT, 65536))
        self.assertEqual(self.read(builder.ROOT*512, len(self.rootfs)), self.rootfs)
        self.assertEqual(self.read(builder.BOOT*512, 512), self.image[:512])
        self.assertEqual(self.read(builder.OVERLAY*512, 13), b"JDTF-EMPTY-v1")
        self.assertEqual(self.read(512, 25), b"reserved-before-partition")

    def test_existing_overlay_is_preserved(self):
        self.assertEqual(self.install(), 0)
        with self.disk.open("r+b") as f:
            f.seek(builder.OVERLAY*512)
            f.write(b"KEEP-USER-DATA")
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.read(builder.OVERLAY*512, 14), b"KEEP-USER-DATA")

    def test_corrupt_or_truncated_input_never_writes(self):
        for image in [self.image[:-1], self.image[:600], self.image[:30],
                      self.image[:530]+bytes([self.image[530]^1])+self.image[531:]]:
            self.assertNotEqual(self.install(image), 0)
            self.assertEqual(self.read(0, 512), bytes(512))

    def test_oversize_header_rejected_before_payload_access(self):
        image = bytearray(self.image)
        struct.pack_into("<I", image, 20, 0xffffff00)
        struct.pack_into("<I", image, 8, 0)
        struct.pack_into("<I", image, 8, zlib.crc32(image[:512]))
        self.assertNotEqual(self.install(bytes(image)), 0)
        self.assertEqual(self.read(0, 512), bytes(512))

    def test_interrupted_upgrade_leaves_tf_boot_invalid(self):
        self.assertEqual(self.install(), 0)
        self.lib.jdtf_test_fail_after(1)
        self.assertNotEqual(self.install(), 0)
        self.assertEqual(self.read(builder.BOOT*512, 512), bytes(512))

    def test_linux_upgrade_writer_and_crc_checks(self):
        self.assertEqual(self.install(), 0)
        image = self.work/"upgrade.bin"
        image.write_bytes(self.image)
        subprocess.run([self.tool, "check", image], check=True)
        subprocess.run([self.tool, "layout", self.disk], check=True)
        version = subprocess.check_output([self.tool, "generation", image], text=True).strip()
        self.assertEqual(version, self.image[68:132].decode())
        subprocess.run([self.tool, "install", image, self.disk], check=True)
        self.assertEqual(self.read(builder.BOOT*512, 512), self.image[:512])
        image.write_bytes(self.image[:-2])
        self.assertNotEqual(subprocess.run([self.tool, "check", image], capture_output=True).returncode, 0)

    def test_linux_writer_refuses_unrelated_card(self):
        image = self.work/"upgrade.bin"
        image.write_bytes(self.image)
        result = subprocess.run([self.tool, "install", image, self.disk], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.read(0, 512), bytes(512))


class ImageFormatTest(unittest.TestCase):
    def test_uimage_header_and_payload_corruption(self):
        data = builder.uimage(b"test payload")
        builder.parse_uimage(data)
        for index in [8, 65]:
            broken = bytearray(data)
            broken[index] ^= 1
            with self.assertRaises(ValueError):
                builder.parse_uimage(broken)

    def test_appended_tree_only_changes_chosen(self):
        strings = b"compatible\0bootargs\0"
        def node(s): return struct.pack(">I", 1)+builder.pad(s+b"\0", 4)
        def prop(value, offset): return struct.pack(">3I", 3, len(value), offset)+builder.pad(value, 4)
        end = struct.pack(">I", 2)
        tree = (node(b"")+prop(builder.BOARD+b"\0", 0)+node(b"chosen")+
                prop(b"console=old\0", 11)+end+node(b"factory-preserve")+end+end+struct.pack(">I", 9))
        h = struct.pack(">10I", 0xd00dfeed, 56+len(tree)+len(strings), 56, 56+len(tree), 40, 17, 16, 0, len(strings), len(tree))
        dtb = builder.patch_dtb(h+bytes(16)+tree+strings, 1234)
        self.assertIn(b"factory-preserve\0", dtb)
        self.assertIn(builder.BOARD+b"\0", dtb)
        self.assertIn(b"linux,initrd-start\0", dtb)
        self.assertIn(struct.pack(">I", 0x08000040+1234), dtb)
        self.assertNotIn(b"console=old", dtb)
        self.assertEqual(struct.unpack_from(">I", dtb, 4)[0], len(dtb))


class OverlayMigrationTest(unittest.TestCase):
    def test_web_upgrade_preserves_config_and_data_not_old_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            lower, overlay = base/"lower", base/"overlay"
            (lower/"etc").mkdir(parents=True)
            (lower/"etc/jdtf-generation").write_text("new\n")
            (overlay/"upper/etc/config").mkdir(parents=True)
            (overlay/"upper/etc/config/network").write_text("user-network")
            (overlay/"upper/lib/modules/old").mkdir(parents=True)
            (overlay/"upper/lib/modules/old/stale.ko").write_text("old-module")
            (overlay/"data").mkdir()
            (overlay/"data/user-file").write_text("user-data")
            (overlay/".jdtf-generation").write_text("old\n")
            subprocess.run(["sh", "-c", '. "$1"; jdtf_migrate_overlay "$2" "$3"',
                            "sh", str(REPO/"tf/overlay.sh"), str(lower), str(overlay)], check=True)
            self.assertEqual((overlay/"upper/etc/config/network").read_text(), "user-network")
            self.assertFalse((overlay/"upper/lib/modules/old/stale.ko").exists())
            self.assertEqual((overlay/"data/user-file").read_text(), "user-data")
            self.assertEqual((overlay/".jdtf-generation").read_text(), "new\n")

    def test_replays_ready_migration_after_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);lower=base/"lower";overlay=base/"overlay"
            (lower/"etc").mkdir(parents=True)
            (lower/"etc/jdtf-generation").write_text("new\n")
            (overlay/".jdtf-migrate/etc/config").mkdir(parents=True)
            (overlay/".jdtf-migrate/etc/config/network").write_text("saved-before-interruption")
            (overlay/".jdtf-migration-ready").touch()
            (overlay/".jdtf-generation").write_text("old\n")
            subprocess.run(["sh", "-c", '. "$1"; jdtf_migrate_overlay "$2" "$3"',
                            "sh", str(REPO/"tf/overlay.sh"), str(lower), str(overlay)], check=True)
            self.assertEqual((overlay/"upper/etc/config/network").read_text(), "saved-before-interruption")
            self.assertFalse((overlay/".jdtf-migration-ready").exists())
