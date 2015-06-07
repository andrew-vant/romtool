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


class Address(object):
    """ Manage and convert between rom offsets and pointer formats."""

    def __init__(self, offset, schema="offset"):
        funcname = "_from_{}".format(schema)
        converter = getattr(self, funcname)
        self._address = converter(offset)

    @property
    def rom(self):
        """ Use this address as a ROM offset. """
        return self._address

    @property
    def hirom(self, mirror=0xC00000):
        """ Use this address as a hirom pointer.

        Use this when writing pointers back to a hirom image. There are
        multiple rom mirrors in hirom; this defaults to using the C0-FF
        mirror, since it contains all possible banks.
        """
        # hirom has multiple possible re-referencings, but C0-FF should
        # always be safe.
        return self._address | mirror

    @classmethod
    def _from_offset(cls, offset):
        """ Initialize an address from a ROM offset. """
        return offset

    @classmethod
    def _from_hirom(cls, offset):
        """ Initialize an address from a hirom pointer. """
        # hirom has multiple mirrors, but I *think* this covers all of them...
        return offset % 0x400000


def hexify(i, length=None):
    """ Converts an integer to a hex string.

    If bitlength is provided, the string will be padded enough to represent
    at least bitlength bits, even if those bits are all zero.
    """
    if length is None:
        return hex(i)

    numbytes = length // 8
    if length % 8 != 0:  # Check for partial bytes
        numbytes += 1
    digits = numbytes * 2  # Two hex digits per byte
    fmtstr = "0x{{:0{}X}}".format(digits)
    return fmtstr.format(i)


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
