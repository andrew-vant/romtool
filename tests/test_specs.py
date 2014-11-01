import unittest
import os
import sys
import logging
from tempfile import TemporaryFile, NamedTemporaryFile
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

class TestTableItemReader(unittest.TestCase):

    requiredfields = "fid", "label", "offset", "size", "type", "tags", "comment"
    testvals = "fld1", "Field", "0x0000", "1", "int.le", "", "no comment."

    def setUp(self):
        self.f = TemporaryFile("w+")

    def test_tableitem_read(self):
        reader = specs.TableItemReader(self.f)
        self.f.write("\r\n".join([",".join(self.requiredfields),
                                 ",".join(self.testvals)]))
        self.f.seek(0)
        self.assertEqual(list(next(reader).items()),
                         list(zip(self.requiredfields, self.testvals)))

    def test_tableitem_int_default(self):
        reader = specs.TableItemReader(self.f)
        testvals = "fld1", "Field", "0x0000", "1", "int", "", "no comment."
        self.f.write("\r\n".join([",".join(self.requiredfields),
                                 ",".join(testvals)]))
        self.f.seek(0)
        self.assertTrue(next(reader)['type'] == 'int.le')

    def test_tableitem_malformed_header(self):
        reader = specs.TableItemReader(self.f)
        header = ",".join(self.requiredfields[1:])
        content = ",".join(self.testvals[1:])
        self.f.write("\r\n".join([header, content]))
        self.f.seek(0)
        self.assertRaises(specs.SpecFieldMismatch,
                          lambda reader: next(reader),
                          reader)

    def tearDown(self):
        self.f.close()


class TestTableReader(unittest.TestCase):

    tablefields = "name", "spec", "entries", "entrysize", "offset", "comment"
    tableheader = ",".join(tablefields)
    specfields = "fid", "label", "offset", "size", "type", "tags", "comment"
    specheader = ",".join(specfields)

    def setUp(self):
        # We need files for both the table itself and the contents specification
        # it links to. The latter must be a named file that gets closed and left
        # alone, so that the tests can re-open it later.

        self.tf = TemporaryFile("w+")
        self.sf = NamedTemporaryFile("w+", delete=False)
        self.sfname = self.sf.name # Not sure if I can access this after close.

        self.tablecontents = "table1", self.sfname, "1", "80", "0x80", "test"
        self.speccontents = "level", "Level", "0x00", "2", "int.le", "", "test"

        self.tf.write("\r\n".join([self.tableheader, ",".join(self.tablecontents)]))
        self.sf.write("\r\n".join([self.specheader, ",".join(self.speccontents)]))
        self.tf.seek(0)
        self.sf.close() # So it can be reopened by TableReader when needed.

    def test_tablereader_read(self):
        reader = specs.TableReader(self.tf)
        self.assertEqual(list(next(reader).items()),
                         list(zip(self.tablefields, self.tablecontents)))

    def test_tablereader_spec_attachment(self):
        reader = specs.TableReader(self.tf)
        table = next(reader)
        self.assertEqual(list(table.spec[0].items()),
                         list(zip(self.specfields, self.speccontents)))

    def test_tablereader_real_files(self):
        specfolder = "tests/specfiles/7th Saga"
        olddir = os.getcwd()
        os.chdir(specfolder)
        with open("tables.csv") as f:
            tables = list(specs.TableReader(f))
        self.assertEqual(tables[1]['name'], "armor")
        self.assertEqual(tables[2]['offset'], "0x72F4")
        self.assertEqual(tables[0].spec[2]['label'], "Power")
        self.assertEqual(tables[1].spec[0]['fid'], "grd")
        os.chdir(olddir)

    def tearDown(self):
        os.remove(self.sfname)
        self.tf.close()

