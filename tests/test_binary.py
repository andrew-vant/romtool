import logging
import unittest
import ureflib.binary as binary

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

if __name__ == '__main__':
    unittest.main()

