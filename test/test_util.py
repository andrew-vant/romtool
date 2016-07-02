import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import romlib
from romlib import util


class TestUtilFuncs(unittest.TestCase):
    def test_tobits_bytes(self):
        s = "8"
        self.assertEqual(util.tobits(s), 64)

    def test_tobits_bits(self):
        s = "b8"
        self.assertEqual(util.tobits(s), 8)

    def test_tobits_malformed_input(self):
        s = "q8"
        self.assertRaises(ValueError, util.tobits, s)

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

    def test_hexify(self):
        self.assertEqual(util.hexify(4), "0x4")

    def test_hexify_bitlength(self):
        self.assertEqual(util.hexify(4, 8), "0x04")

    def test_hexify_partial_byte(self):
        self.assertEqual(util.hexify(4, 5), "0x04")


class TestOrderedDictReader(unittest.TestCase):
    def test_read_ordereddict_field_order(self):
        with TemporaryFile("w+") as f:
            keys = ["f{}".format(i) for i in range(8)]
            vals = [str(i) for i in range(8)]
            keyline = ",".join(keys)
            valline = ",".join(vals)
            f.write("\r\n".join([keyline, valline]))
            f.seek(0)
            reader = util.OrderedDictReader(f)
            self.assertEqual(list(next(reader).keys()), keys)
