import logging
import unittest
import ureflib.binary as binary
from tempfile import TemporaryFile

class TestBinaryFunctions(unittest.TestCase):

    def test_unpack_tinyint(self):
        # I'm keeping track of numbers in binary because it makes it easier to
        # see what the correct answer "should" be.
        ti = 0b10101100

        # Test a single full byte in default format.
        self.assertEqual(binary.unpack_tinyint(ti), ti)

        # Test offset and width.
        self.assertEqual(binary.unpack_tinyint(ti, 1, 3, "big"), 0b010)

        # Test little endian.
        self.assertEqual(binary.unpack_tinyint(ti, 4, 3, "little"), 0b011)

        # Test sanity checks.
        self.assertRaises(ValueError, binary.unpack_tinyint, 10000)
        self.assertRaises(IndexError, binary.unpack_tinyint, ti, offset=-1)
        self.assertRaises(IndexError, binary.unpack_tinyint, ti, offset=6, width=8)
        self.assertRaises(ValueError, binary.unpack_tinyint, ti, width=-1)
        self.assertRaises(ValueError, binary.unpack_tinyint, ti, bitorder="fail")

    def test_unpack_flag(self):
        byte = 12 # (b00001100)
        expected_results = [False, False, False, False, True, True, False, False]
        results = [binary.unpack_flag(12, bit) for bit in range(8)]
        self.assertEqual(results, expected_results)

    def test_unpack_bitfield(self):
        self.assertEqual(binary.unpack_bitfield(12), "00001100")


class TestRead(unittest.TestCase):

    def setUp(self):
        self.f = TemporaryFile("wb+")
        data = 0xFF00FF00FF00FF00
        dbytes = data.to_bytes((data.bit_length()-1) // 8 + 1, byteorder='big')
        assert(len(dbytes) == 8) # Ran into trouble with this.
        self.f.write(dbytes)

        # I'm only going to bother setting the values that read actually uses
        self.flag = {
            "type":       "bitfield",
            "offset":     "2.1",
            "width":      "0.1"
        }

        self.intbe = {
            "type":      "int.be",
            "offset":    "3",
            "width":     "2"
        }

        self.intle = {
            "type":      "int.le",
            "offset":    "3",
            "width":     "2"
        }

        self.int = {
            "type":      "int",
            "offset":    "3",
            "width":     "2"
        }

        self.bitfield = {
            "type":    "bitfield",
            "offset":  "0",
            "width":   "6"
        }

        self.ti_le = {
            "type":       "ti.le",
            "offset":     "3.2",
            "width":      "0.3"
        }

        self.ti_be = {
            "type":       "ti.be",
            "offset":     "3.2",
            "width":      "0.3"
        }

    def test_normal_reads(self):
        self.assertEqual(binary.read(self.f, self.flag, 0), '1')
        self.assertEqual(binary.read(self.f, self.flag, 1), '0')
        self.assertEqual(binary.read(self.f, self.intbe, 1), 0xFF00)

    def tearDown(self):
        self.f.close()

if __name__ == '__main__':
    unittest.main()

