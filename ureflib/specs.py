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


class StructFieldReader(SpecReader):

    requiredfields = "id", "label", "size", "type", "tags", "comment"

    def transform(self, item):
        # All sizes are represented internally as bits, so convert as needed.
        item['size'] = tobits(item['size'])
        # Tags are helpful.
        item.tags = {s for s in item['tags'].split("|") if s}

    def validate(self, item):
        # Should have a regex to recognize leading b for bits here, in size.
        pass

class ArrayReader(SpecReader):

    requiredfields = "name", "type", "offset", "length", "stride", "comment"

    def transform(self, arr):
        with open(arr["type"]) as f:
            arr.struct = list(StructFieldReader(f))
        return arr

def tobits(size):
    """ Convert a size specifier to number of bits. """
    isbits = size.startswith('b')
    if isbits:
        bits = int(size[1:])
    else:
        bits = int(size) * 8
    return bits
