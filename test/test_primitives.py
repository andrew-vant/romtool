""" Test primitive types

NOTE: primitive.py is defunct, but I might want to reference it before release
so I haven't removed it yet. For now, always skip these tests.
"""
import unittest

raise unittest.SkipTest("Skipping primitive tests (testing dead code)")

import romtool.primitives as primitives

@unittest.skip
class TestFlag(unittest.TestCase):
    def test_flag_creation(self):
        f = Flag(0)
        self.assertFalse(f)
        f = Flag(1)
        self.assertTrue(f)
        f = Flag(False)
        self.assertFalse(f)
        f = Flag(True)
        self.assertTrue(f)


@unittest.skip
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


@unittest.skip
class TestUtils(unittest.TestCase):
    def test_get_int(self):
        self.assertIs(primitives.getcls('uint'), Int)
    def test_get_bin(self):
        self.assertIs(primitives.getcls('bin'), Bin)
    def test_get_flag(self):
        self.assertIs(primitives.getcls('flag'), Flag)
    def test_get_invalid_type(self):
        self.assertRaises(KeyError, primitives.getcls, 'thingy')



