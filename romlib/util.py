import csv
from collections import OrderedDict
from types import SimpleNamespace

class OrderedDictReader(csv.DictReader):
    """ Read a csv file as a list of ordered dictionaries.

    This has one additional option over DictReader, "orderfunc", which
    specifies a sorting key over a dictionary's items. If it is not provided,
    the dictionary items will be sorted in the same order as the csv's columns.
    This makes it possible to re-write the same file without interfering with
    its column order.

    Note that a corresponding OrderedDictWriter is not needed; supply an
    ordered dictionary's .keys() as the fieldnames for a regular DictWriter.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orderfunc = kwargs.get("orderfunc",
                                     lambda t: self.fieldnames.index(t[0]))

    def __next__(self):
        d = super().__next__()
        return OrderedDict(sorted(d.items(), key=self._orderfunc))


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
            err = ValueError(msg.format(overlap))
            err.overlap = overlap
            raise err

    out = type(dicts[0])()  # To account for OrderedDicts
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

def flatten(obj):
    flat = SimpleNamespace()
    for k, v in vars(obj).items():
        if not hasattr(v, '__dict__'):
            setattr(flat, k, v)
        else:
            for k, v in vars(flatten(v)).items():
                setattr(flat, k, v)
    return flat
