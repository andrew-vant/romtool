import csv
from collections import OrderedDict

from .exceptions import SpecFieldMismatch

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


def validate_spec(spec):
    if not all(prop in spec for prop in spec.requiredproperties):
        raise SpecFieldMismatch(
            "Creating spec: {}".format(spec.__class__.__name__),
            spec.requiredproperties,
            list(spec.keys()))

def merge_dicts(dicts, allow_overlap=False):
    if not dicts:
        return {}
    if len(dicts) == 1:
        return dicts[0]
    if not allow_overlap:
        keys = [set(d.keys()) for d in dicts]
        overlap = keys[0].intersection(*keys)
        if overlap:
            msg = "Attempt to merge dicts with overlapping keys, keys were: {}"
            raise ValueError(msg.format(overlap))

    out = type(dicts[0])() # To account for OrderedDicts
    for d in dicts:
        out.update(d)
    return out

def tobits(size):
    """ Convert a size specifier to number of bits. """
    isbits = size.startswith('b')
    if isbits:
        bits = int(size[1:])
    else:
        bits = int(size, 0) * 8
    return bits

