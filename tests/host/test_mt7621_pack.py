import importlib.util
import unittest
from pathlib import Path
spec = importlib.util.spec_from_file_location("packer", Path(__file__).resolve().parents[2] / "tools/mt7621_pack.py")
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)

class PackTest(unittest.TestCase):
    def test_padding_matches_binman_layout(self):
        spl, payload = b"S" * 65537, b"PAYLOAD"
        image = packer.pack(spl, payload, 65536)
        self.assertEqual(image[:len(spl)], spl)
        self.assertEqual(image[len(spl):131072], b"\xff" * 65535)
        self.assertEqual(image[131072:], payload)

    def test_aligned_input_has_no_extra_block(self):
        self.assertEqual(packer.pack(b"ABCD", b"EF", 4), b"ABCDEF")

    def test_no_spl(self):
        self.assertEqual(packer.pack(b"", b"PAYLOAD", 1), b"PAYLOAD")

    def test_invalid_alignment(self):
        for alignment in (0, -1, 3):
            with self.assertRaises(ValueError):
                packer.pack(b"S", b"P", alignment)
