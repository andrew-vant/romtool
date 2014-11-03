import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import ureflib
from ureflib import util

class TestUtilFuncs(unittest.TestCase):
    def test_validate_spec(self):
        d = OrderedDict({"fld1": 1, "fld2": 2, "fld3": 3})
        d.requiredproperties = "fld1","fld2","fld3","fld4"
        self.assertRaises(util.SpecFieldMismatch, util.validate_spec, d)

    def test_tobits_bytes(self):
        s = "8"
        self.assertEqual(util.tobits(s), 64)

    def test_tobits_bits(self):
        s = "b8"
        self.assertEqual(util.tobits(s), 8)

    def test_tobits_malformed_input(self):
        s = "q8"
        self.assertRaises(ValueError, util.tobits, s)


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

