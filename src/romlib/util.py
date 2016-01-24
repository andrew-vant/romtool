""" Various utility functions used in romlib."""

import csv
import contextlib
from collections import OrderedDict


class OrderedDictReader(csv.DictReader):  # pylint: disable=R0903
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
        d = super().__next__()  # pylint: disable=invalid-name
        return OrderedDict(sorted(d.items(), key=self._orderfunc))

@contextlib.contextmanager
def loading_context(listname, name, index=None):
    """ Context manager for loading lists or files.

        listname -- a name for the list or file being iterated over.
        name     -- a name for the specific item being loaded.
        index    -- The index of the item being loaded. Typically a linenum.
    """
    if index is None:
        index = "Unknown"
    try:
        yield
    except Exception as ex:
        msg = "{}\nProblem loading {} #{}: {}"
        msg = msg.format(ex.args[0], listname, index, name)
        ex.args = (msg,) + ex.args[1:]
        raise

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


def remap_od(odict, keymap):
    """ Rename the keys in an ordereddict while preserving their order.

    keymap: A dictionary mapping old key names to new key names.

    keys not in keymap will be left alone.
    """
    newkeys = (keymap.get(k, k) for k in odict.keys())
    return OrderedDict(zip(newkeys, odict.values()))


def merge_dicts(dicts, allow_overlap=False):
    """ Merge an arbitrary number of dictionaries.

    Optionally, raise an exception on key overlap.
    """
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
    for d in dicts:  # pylint: disable=invalid-name
        out.update(d)
    return out


def tobits(size, default=None):
    """ Convert a size specifier to number of bits.

    size should be a string containing a size specifier. e.g. 4 (4 bytes),
    or b4 (4 bits). If size is not a valid size specifier and default is
    not set, ValueError will be raised. If default is set, it will be returned
    for strings that are invalid sizes, such as empty strings.
    """

    isbits = size.startswith('b')
    try:
        if isbits:
            bits = int(size[1:])
        else:
            bits = int(size, 0) * 8
    except ValueError:
        if default is not None:
            bits = default
        else:
            raise
    return bits


def filebytes(f):
    """ Get an iterator over the bytes in a file."""
    byte = f.read(1)
    while byte:
        yield byte[0]
        byte = f.read(1)


def bit_offset(source):
    """ Find the current read position of *source*, in bits.

    Used for cases where *source* may be a file, a bitstring, or a bytes.
    Returns f.tell(), bs.pos, or 0 respectively.
    """
    # Don't like this if chain but try/except comes out worse...
    if hasattr(source, 'tell'):
        return source.tell() * 8
    elif hasattr(source, 'pos'):
        return source.pos
    else:
        return 0


def divup(a, b):  # pylint: disable=invalid-name
    """ Divide A by B with integer division, rounding up instead of down."""
    # Credit to stackoverflow: http://stackoverflow.com/a/7181952/4638839
    return (a + (-a % b)) // b


def intify(x):  # pylint: disable=invalid-name
    """ A forgiving int() cast; returns zero for non-int strings."""
    try:
        return int(x, 0)
    except ValueError:
        return 0
