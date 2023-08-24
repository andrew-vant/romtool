import unittest
from collections import OrderedDict
from itertools import chain
from tempfile import TemporaryFile, NamedTemporaryFile

import romtool
from romtool import util
from romtool.util import FormatSpecifier, HexInt


class TestUtilFuncs(unittest.TestCase):
    def test_merge_dicts(self):
        dicts = [{"key1": "val1"},
                 {"key2": "val2"},
                 {"key3": "val3"},
                 {"key3": "oops"}]
        merged = {"key1": "val1",
                  "key2": "val2",
                  "key3": "val3"}

        self.assertEqual(util.merge_dicts({}), {})
        self.assertEqual(util.merge_dicts([{1: 2}]), {1: 2})
        self.assertEqual(util.merge_dicts(None), {})
        self.assertEqual(util.merge_dicts(dicts[0:3]), merged)
        self.assertRaises(ValueError, util.merge_dicts, dicts[2:])
        merged['key3'] = 'oops'
        self.assertEqual(util.merge_dicts(dicts, True), merged)


class TestHexInt(unittest.TestCase):
    def test_hi_string(self):
        self.assertEqual(str(HexInt(0xDEAD)), "0xDEAD")

    def test_hi_repr_str(self):
        self.assertEqual(repr(HexInt(0xDEAD)), "HexInt(0xDEAD)")

    def test_hi_repr_use(self):
        hi = HexInt(0xBEEF)
        self.assertEqual(hi, eval(repr(hi)))


class TestSequenceView(unittest.TestCase):
    def test_noop_view(self):
        parent = [0, 1, 2, 3]
        view = util.SequenceView(parent)
        self.assertEqual(view, parent)
        self.assertEqual(parent, view)

    def test_view_lookup(self):
        parent = [0, 1, 2, 3]
        view = util.SequenceView(parent)
        for i, v in enumerate(parent):
            self.assertEqual(view[i], v)

    def test_view_slice(self):
        parent = [0, 1, 2, 3]
        view = util.SequenceView(parent)[:2]
        self.assertEqual(view, [0, 1])
        self.assertEqual(list(view), [0, 1])


class TestChainView(unittest.TestCase):
    def test_noop_chain(self):
        parent = [0, 1, 2]
        schain = util.ChainView(parent)
        self.assertEqual(list(schain), parent)

    def test_multiple_parents(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        schain = util.ChainView(*parents)
        self.assertEqual(list(schain), list(chain(*parents)))
        for a, b in zip(schain, chain(*parents)):
            self.assertEqual(a, b)

    def test_schain_slice(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        schain = util.ChainView(*parents)[2:4]
        self.assertEqual(schain, [2, 3])

    def test_schain_stepped_slice(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        schain = util.ChainView(*parents)[2:5:2]
        self.assertEqual(schain, [2, 4])


class TestFormatSpecifier(unittest.TestCase):
    def test_parse_simple_spec(self):
        spec = FormatSpecifier.parse('d')
        self.assertEqual(str(spec), 'd')

    def test_parse_full_spec(self):
        spec = FormatSpecifier.parse('0>#10_.2f')
        self.assertEqual(spec.fill, '0')
        self.assertEqual(spec.align, '>')
        self.assertEqual(spec.sign, None)
        self.assertEqual(spec.alt, True)
        self.assertEqual(spec.zero_pad, False)
        self.assertEqual(spec.width, 10)
        self.assertEqual(spec.grouping_option, '_')
        self.assertEqual(spec.precision, 2)
        self.assertEqual(spec.type, 'f')
        self.assertEqual(str(spec), '0>#10_.2f')

    def test_parse_empty_spec(self):
        spec = FormatSpecifier.parse('')
        self.assertEqual(str(spec), '')

    def test_parse_invalid_spec(self):
        with self.assertRaises(ValueError):
            FormatSpecifier.parse('invalid_spec')

    def test_str_method(self):
        spec = FormatSpecifier(fill='0', align='>', width=10,
                               precision=2, type='f')
        self.assertEqual(str(spec), '0>10.2f')
