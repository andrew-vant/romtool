import logging
import csv
from collections import namedtuple, OrderedDict

class SpecException(Exception):
    pass


class SpecFieldMismatch(SpecException):

    def __init__(self, message, required, provided):
        super().__init__(message)
        self.message = message
        self.required = required
        self.provided = provided

    def __str__(self):
        reqstr = "Fields required: {}".format(self.required)
        provstr = "Fields provided: {}".format(self.provided)
        return "\n".join([self.message, reqstr, provstr])


def load_tables(filename):
    """ Load a list of tables present in a ROM. """
    with open(filename, "rb") as f:
        return list(TableReader(f))


class OrderedDictReader(csv.DictReader):
    """ Read a csv file as a list of ordered dictionaries.

    This has one additional option over DictReader, "orderfunc", which specifies
    an sorting key over a dictionary's items. If it is not provided, the dictionary
    items will be sorted in the same order as the csv's columns. This makes it
    possible to re-write the same file without interfering with its column
    order.

    Note that a corresponding OrderedDictWriter is not needed; supply an ordered
    dictionary's .keys() as the fieldnames for a regular DictWriter.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orderfunc = kwargs.get("orderfunc",
                                     lambda t: self.fieldnames.index(t[0]))
    def __next__(self):
        d = super().__next__()
        return OrderedDict(sorted(d.items(), key=self._orderfunc))


class SpecReader(OrderedDictReader):
    requiredfields = []
    def __init__(self, *args, requiredfields=None, **kwargs):
        super().__init__(*args, **kwargs)
        if requiredfields is not None:
            self.requiredfields = requiredfields

    def __next__(self):
        spec = super().__next__()
        self.validate(spec)
        self.transform(spec)
        return spec

    def transform(self, item): # Inheriting classes should override this.
        pass

    def validate(self, item): # And this?
        if not all(field in item for field in self.requiredfields):
            raise SpecFieldMismatch(
                "Spec appears to be missing fields.",
                self.requiredfields,
                list(item.keys()))


class TableItemReader(SpecReader):

    requiredfields = "fid", "label", "offset", "size", "type", "tags", "comment"

    def transform(self, item):
        if item['type'] == "flag": # Flag is just an alias for a width-1 bf.
            item['type'] = "bitfield"
            item['width'] = "0.1"
        if item['type'] == "int": # Int defaults to little endian.
            item['type'] = "int.le"


class TableReader(SpecReader):

    requiredfields = "name", "spec", "entries", "entrysize", "offset", "comment"

    def transform(self, table):
        with open(table["spec"]) as f:
            table.spec = list(TableItemReader(f))
        return table

