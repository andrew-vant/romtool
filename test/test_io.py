from unittest import TestCase

from bitarray import bitarray
from bitarray.util import hex2ba, ba2hex

from romtool.io import BitArrayView, Unit

class TestBAVBasics(TestCase):
    def setUp(self):
        self.hex = 'abcdef'
        self.ba = hex2ba(self.hex)
        self.view = BitArrayView(self.ba)

    def test_init(self):
        self.assertTrue(self.view)

    def test_bits(self):
        self.assertEqual(self.view.bits, self.ba)

    def test_length(self):
        self.assertEqual(len(self.view), len(self.hex)*4)

    def test_bounds(self):
        self.assertEqual(self.view.offset, 0)
        self.assertEqual(self.view.end, len(self.view))
        self.assertEqual(self.view.abs_start, 0)
        self.assertEqual(self.view.abs_end, len(self.view))

    def test_parent(self):
        child = BitArrayView(self.view)
        self.assertIsNone(self.view.parent)
        self.assertIs(child.parent, self.view)

class TestBAVSlicing(TestCase):
    def setUp(self):
        self.hex = 'abcdef'
        self.ba = hex2ba(self.hex)
        self.parent = BitArrayView(self.ba)
        self.noop = BitArrayView(self.parent)
        self.right = self.parent[8:]
        self.left = self.parent[:-8]
        self.both = self.parent[8:-8]

    def test_slice_length(self):
        plen = len(self.parent)
        tests = [('noop',  self.noop,  plen),
                 ('right', self.right, plen-8),
                 ('left',  self.left,  plen-8),
                 ('both',  self.both,  plen-16)]
        for tid, child, expected in tests:
            with self.subTest(sl=tid):
                self.assertEqual(len(child), expected)

    def test_slice_content(self):
        tests = [('noop',  self.noop,  'abcdef'),
                 ('right', self.right, 'cdef'),
                 ('left',  self.left,  'abcd'),
                 ('both',  self.both,  'cd')]
        for tid, child, expected in tests:
            with self.subTest(sl=tid):
                self.assertEqual(ba2hex(child.bits), expected)

    def test_abs_bounds(self):
        tests = [('noop',  self.noop,  0, 24),
                 ('right', self.right, 8, 24),
                 ('left',  self.left,  0, 16),
                 ('both',  self.both,  8, 16)]
        for tid, child, start, end in tests:
            with self.subTest(sl=tid, start=start):
                self.assertEqual(child.abs_start, start)
            with self.subTest(sl=tid, end=end):
                self.assertEqual(child.abs_end, end)

    def test_child_writes(self):
        self.both.bits = hex2ba('00')
        tests = [('noop',  self.noop,  'ab00ef'),
                 ('right', self.right, '00ef'),
                 ('left',  self.left,  'ab00'),
                 ('both',  self.both,  '00')]
        for tid, child, expected in tests:
            with self.subTest(sl=tid):
                self.assertEqual(ba2hex(child.bits), expected)

    def test_byte_slicing(self):
        child = self.parent[0:2:Unit.bytes]
        self.assertEqual(ba2hex(child.bits),  'abcd')
        child = self.parent[1::Unit.bytes]
        self.assertEqual(ba2hex(child.bits), 'cdef')


class TestBAVInterpretation(TestCase):
    def setUp(self):
        self.ba1 = hex2ba('0000')
        self.ba2 = hex2ba('FF00')
        self.view1 = BitArrayView(self.ba1)
        self.view2 = BitArrayView(self.ba2)

    def test_bad_input_length(self):
        bad = hex2ba('')
        with self.assertRaises(ValueError):
            self.view2.bits = bad

    def test_hex(self):
        self.assertEqual(self.view1.hex, '0000')
        self.assertEqual(self.view2.hex.upper(), 'FF00')
        self.view2.hex = '00FF'
        self.assertEqual(self.view2.hex.upper(), '00FF')
        self.assertEqual(self.view2.bits, hex2ba('00FF'))

    def test_uint(self):
        self.assertEqual(self.view1.uint, 0)
        self.assertEqual(self.view2.uint, 0xFF00)
        self.view2.uint = 0x00FF
        self.assertEqual(self.view2.uint, 0x00FF)
        self.assertEqual(self.view2.bits, hex2ba('00FF'))

    def test_uintbe(self):
        self.assertEqual(self.view1.uintbe, 0)
        self.assertEqual(self.view2.uintbe, 0xFF00)
        self.view2.uintbe = 0x00FF
        self.assertEqual(self.view2.uintbe, 0x00FF)
        self.assertEqual(self.view2.bits, hex2ba('00FF'))

    def test_uintle(self):
        self.assertEqual(self.view1.uintle, 0)
        self.assertEqual(self.view2.uintle, 0x00FF)
        self.view2.uintle = 0xFF00
        self.assertEqual(self.view2.uintle, 0xFF00)
        self.assertEqual(self.view2.bits, hex2ba('00FF'))

    def test_bytes(self):
        self.assertEqual(self.view1.bytes, b'\x00\x00')
        self.assertEqual(self.view2.bytes, b'\xFF\x00')
        self.view2.bytes = b'\x00\xFF'
        self.assertEqual(self.view2.bytes, b'\x00\xFF')
        self.assertEqual(self.view2.bits, hex2ba('00FF'))
