import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import romtool
from romtool import util
from romtool.util import HexInt


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
