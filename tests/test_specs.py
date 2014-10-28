import unittest
from tempfile import TemporaryFile
import ureflib.specs as specs

class TestOrderedDictReader(unittest.TestCase):

    def test_read_ordereddict_field_order(self):
        with TemporaryFile("w+") as f:
            keys = ["f{}".format(i) for i in range(8)]
            vals = [str(i) for i in range(8)]
            keyline = ",".join(keys)
            valline = ",".join(vals)
            f.write("\r\n".join([keyline, valline]))
            f.seek(0)
            reader = specs.OrderedDictReader(f)
            self.assertEqual(list(next(reader).keys()), keys)

class TestSpecReader(unittest.TestCase):
    
    def setUp(self):
        self.f = TemporaryFile("w+")
        self.fields = ["f1", "f2", "f3"]
        self.vals = [str(i) for i in range(len(self.fields))]
        
    def helper_writeout(self, fields, vals):
        header = ",".join(fields)
        content = ",".join(vals)
        self.f.write("\r\n".join([header, content]))
        self.f.seek(0)
        
    def test_specreader_read(self):
        # This is mostly to be sure we haven't broken existing functionality. 
        
        self.helper_writeout(self.fields, self.vals)
        reader = specs.SpecReader(self.f, requiredfields=self.fields)
        self.assertEqual(list(next(reader).items()), 
                         list(zip(self.fields, self.vals)))
        
    def test_specreader_missing_fields(self):
        self.helper_writeout(self.fields[1:], self.vals[1:])
        reader = specs.SpecReader(self.f, requiredfields=self.fields)
        self.assertRaises(specs.SpecFieldMismatch,
                          lambda reader: next(reader),
                          reader)

    def tearDown(self):
        self.f.close()

