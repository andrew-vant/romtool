import unittest

import bitstring

from romlib.primitives import UInt, BinCodec, Bin


class TestUInt(unittest.TestCase):
    def test_uint_creation(self):
        uint = UInt(0)
        uint = UInt(1)
        uint = UInt(5)
        uint = UInt(200000)
        self.assertIsInstance(uint, UInt)
        self.assertIsInstance(uint, int)

    def test_uint_comparison(self):
        i = UInt(5)
        self.assertGreater(i, 4)
        self.assertEqual(i, 5)
        self.assertLess(i, 6)

    def test_uint_nonhex_str(self):
        i = UInt(5)
        self.assertEqual(str(i), str(5))

    def test_uint_hex_str(self):
        i = UInt(5, display='hex')
        self.assertEqual(str(i), '0x05')

    def test_uint_size_check(self):
        checks = [(0, 0, False),
                  (0, 1, True),
                  (5, 3, True),
                  (0xFF, 8, True), # Largest single-byte int
                  (0x100, 8, False),
                  (0x100, 9, True),
                  (0xFFFF, 16, True),
                  (0x10000, 16, False),
                  (0x10000, 17, True)]

        for value, bits, valid in checks:
            if not valid:
                msg = f"UInt({value}, {bits}) succeeded, but shouldn't have"
                with self.assertRaises(ValueError, msg=msg):
                    UInt(value, bits)
            else:
                try:
                    UInt(value, bits)
                except ValueError as ex:
                    msg = f'UInt({value}, {bits}) raised ValueError unexpectedly'
                    self.fail(msg)


class TestBinCodec(unittest.TestCase):
    def test_bincodec_creation(self):
        codec = BinCodec("abcdefg")
        self.assertIsInstance(codec, BinCodec)

    def test_bincodec_invalid_keystr(self):
        self.assertRaises(ValueError, BinCodec, '!')

    def test_bincodec_encode(self):
        codec = BinCodec('abcd')
        text = "AbCd"
        bools = [True, False, True, False]

        self.assertEqual(codec.encode(bools), text)

    def test_bincodec_decode(self):
        codec = BinCodec('abcd')
        text = "AbCd"
        bools = [True, False, True, False]

        self.assertEqual(codec.decode(text), bools)

    def test_bincodec_lenerr(self):
        codec = BinCodec('abcd')
        text = "AbCd" * 2
        bools = [True, False, True, False] * 2

        self.assertRaises(ValueError, codec.decode, text)
        self.assertRaises(ValueError, codec.encode, bools)


class TestBin(unittest.TestCase):
    def setUp(self):
        self.codec = BinCodec('abcd')

    def test_bin_creation(self):
        bits = Bin()
        self.assertIsInstance(bits, Bin)
        self.assertIsInstance(bits, bitstring.Bits)

    def test_bin_from_fstr(self):
        text = 'AbCd'
        bools = [True, False, True, False]
        bits = Bin('fmt:' + text, self.codec)
        self.assertEqual(bits, bools)

    def test_bin_from_bs_init(self):
        bits = Bin('uint:32=4')
        self.assertEqual(bits.uint, 4)
