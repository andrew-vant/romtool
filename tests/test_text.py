import unittest
from ureflib import text
from tempfile import TemporaryFile

class TestTextTable(unittest.TestCase):
    def setUp(self):
        self.tbl = text.TextTable("tests/map.testrom/texttables/main.tbl")

    def test_basic_encode(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A])
        self.assertEqual(self.tbl.encode(text), binary)

    def test_basic_decode(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A])
        self.assertEqual(self.tbl.decode(binary), text)

    def test_decode_eos(self):
        text = "Esuna[EOS]"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(self.tbl.decode(binary), text)

    def test_decode_without_eos(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(self.tbl.decode(binary, include_eos = False), text)

    def test_decode_miss(self):
        text = "Esuna[$F0][$0A]"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF0, 0x0A])
        self.assertEqual(self.tbl.decode(binary), text)

    def test_eos_override(self):
        text = "Esuna[EOS]00"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(self.tbl.decode(binary, stop_on_eos = False), text)

    def test_readstr(self):
        text = "Esuna[EOS]"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        with TemporaryFile("bw+") as f:
            f.write(binary)
            f.seek(0)
            self.assertEqual(self.tbl.readstr(f), text)
