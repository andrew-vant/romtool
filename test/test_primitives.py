import unittest

import bitstring

import romlib.primitives as primitives
from romlib.primitives import Int, Bin, BinCodec


class TestInt(unittest.TestCase):
    def test_uint_creation(self):
        uint = Int(0)
        uint = Int(1)
        uint = Int(5)
        uint = Int(200000)
        self.assertIsInstance(uint, Int)
        self.assertIsInstance(uint, int)

    def test_uint_comparison(self):
        i = Int(5)
        self.assertGreater(i, 4)
        self.assertEqual(i, 5)
        self.assertLess(i, 6)

    def test_uint_nonhex_str(self):
        i = Int(5)
        self.assertEqual(str(i), str(5))

    def test_uint_hex_str(self):
        results = {
                0:  '0x00',
                5:  '0x05',
                -5: '-0x05',
                0x130:  '0x0130',
                -0x130: '-0x0130',
               }

        for i, s in results.items():
            self.assertEqual(str(Int(i, display='hex')), s)

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
                msg = f"Int({value}, {bits}) succeeded, but shouldn't have"
                with self.assertRaises(ValueError, msg=msg):
                    Int(value, bits)
            else:
                try:
                    Int(value, bits)
                except ValueError as ex:
                    msg = f'Int({value}, {bits}) raised ValueError unexpectedly'
                    self.fail(msg)

    def test_mod(self):
        i = Int(0)
        self.assertEqual(i.mod(5), 5)

    def test_unmod(self):
        i = Int(0)
        self.assertEqual(i.unmod(5), -5)


class TestBinCodec(unittest.TestCase):
    def test_bincodec_creation(self):
        codec = BinCodec("abcdefg")
        self.assertIsInstance(codec, BinCodec)

    def test_bincodec_registry(self):
        c1 = BinCodec.get("abcdefg")
        c2 = BinCodec.get("abcdefg")
        self.assertIsInstance(c1, BinCodec)
        self.assertIs(c1, c2)

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

    def test_bin_from_str(self):
        text = 'AbCd'
        bools = [True, False, True, False]
        bits = Bin(text, len(text), 'abcd')
        self.assertEqual(bits, bools)

    def test_bin_from_bs_init(self):
        bits = Bin('uint:32=4')
        self.assertEqual(bits.uint, 4)

    def test_mod(self):
        inbits = Bin('0b1010')
        outbits = Bin('0b0101')
        self.assertEqual(inbits.mod('lsb0'), outbits)
        self.assertEqual(outbits.unmod('lsb0'), inbits)
        self.assertEqual(inbits.mod(''), inbits)

    def test_str(self):
        bits = Bin('0b1010')
        self.assertEqual(str(bits), '0b1010')

    def test_str_from_bits(self):
        text = 'AbCd'
        bits = Bin(text, display='abcd')
        self.assertEqual(str(bits), text)


class TestUtils(unittest.TestCase):
    def test_get_int(self):
        self.assertIs(primitives.getcls('uint'), Int)
    def test_get_bin(self):
        self.assertIs(primitives.getcls('bin'), Bin)
    def test_get_invalid_type(self):
        self.assertRaises(KeyError, primitives.getcls, 'thingy')

