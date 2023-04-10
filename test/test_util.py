import unittest
from collections import OrderedDict
from itertools import chain
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


class TestSequenceView(unittest.TestCase):
    def test_noop_view(self):
        parent = [0, 1, 2, 3]
        view = util.SequenceView(None, parent)
        self.assertEqual(view, parent)
        self.assertEqual(parent, view)

    def test_sliced_view(self):
        parent = [0, 1, 2, 3]
        view = util.SequenceView(slice(0, 2), parent)
        self.assertEqual(view, [0, 1])
        self.assertEqual(list(view), [0, 1])

    def test_multiple_parents(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        view = util.SequenceView(None, *parents)
        self.assertEqual(view, list(chain(*parents)))

    def test_multiple_parents_sliced(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        view = util.SequenceView(slice(2, 4), *parents)
        self.assertEqual(view, [2, 3])

    def test_view_from_view(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        view = util.SequenceView(None, *parents)[2:4]
        self.assertEqual(view, [2, 3])

    def test_view_with_step(self):
        parents = [[0, 1, 2], [3, 4, 5]]
        view = util.SequenceView(None, *parents)[1:5:2]
        self.assertEqual(list(view), [1, 3])
        self.assertEqual(view, [1, 3])
