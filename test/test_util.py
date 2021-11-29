import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import romlib
from romlib import util


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
