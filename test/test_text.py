import unittest
from romlib import text
from tempfile import TemporaryFile

# FIXME: This should really use a dummy ROM rather than a real one.

class TestTextTable(unittest.TestCase):
    def setUp(self):
        self.codec = 'main'
        self.ttfile = "src/romtool/maps/7th Saga (US)/texttables/main.tbl"
        with open(self.ttfile) as f:
            self.tbl = text.add_tt(self.codec, f)

    def test_basic_encode(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A])
        self.assertEqual(text.encode(self.codec), binary)

    def test_basic_decode(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A])
        self.assertEqual(binary.decode(self.codec), text)

    def test_decode_eos(self):
        text = "Esuna[EOS]"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(binary.decode(self.codec), text)

    def test_decode_clean(self):
        text = "Esuna"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(binary.decode(self.codec+'-clean'), text)

    def test_decode_miss(self):
        text = "Esuna[$F0][$0A]"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF0, 0x0A])
        self.assertEqual(binary.decode(self.codec), text)

    @unittest.skip("Test not implemented yet.")
    # Note to self, separately test for raw hex encode (which should work)
    # and no valid encoding (which should fail)
    def test_encode_miss(self):
        pass

    def test_eos_override(self):
        text = "Esuna[EOS]00"
        binary = bytes([0x24, 0x4C, 0x4E, 0x47, 0x3A, 0xF7, 0x00, 0x00])
        self.assertEqual(text.encode(f'{self.codec}-raw'), binary)
