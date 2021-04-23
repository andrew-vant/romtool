""" Various utility functions used in romlib."""

import csv
import contextlib
import logging
import os
from collections import OrderedDict
from os.path import dirname, realpath
from os.path import join as pathjoin
from math import ceil

import yaml
import asteval
from bitarray import bitarray


log = logging.getLogger(__name__)
libroot = dirname(realpath(__file__))

# romtool's expected format is tab-separated values, no quoting, no
# escaping (i.e. tab literals aren't allowed)

csv.register_dialect(
        'romtool',
        delimiter='\t',
        lineterminator=os.linesep,
        quoting=csv.QUOTE_NONE,
        strict=True,
        )


class CheckedDict(dict):
    """ A dictionary that warns you if you overwrite keys."""

    cmsg = "Conflict: %s: %s replaced with %s."

    def __setitem__(self, key, value):
        self._check_conflict(key, value)
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        d = dict(*args, **kwargs)
        for k, v in d.items():
            self._check_conflict(k, v)
        super().update(d)

    def _check_conflict(self, key, value):
        if key in self and value != self[key]:
            logging.debug(self.cmsg, key, self[key], value)


class HexInt(int):
    """ An int that always prints as hex

    Suitable for printing offsets.
    """
    def __new__(cls, value, sz_bits=None):
        if isinstance(value, str):
            value = int(value, 0)
        self = int.__new__(cls, value)
        self.sz_bits = sz_bits

    def __str__(self):
        """ Print self as a hex representation of bytes """
        # two digits per byte; bytes are bits/8 rounding up.
        digits = ceil(self.sz_bits / 8) * 2
        sign = '-' if self < 0 else ''
        return f'{sign}0x{abs(self):0{digits}X}'


class PrettifierMixin:
    """ Provides the .pretty method and sets up yaml representers for it """
    class _PrettyDumper(yaml.Dumper):
        """ Mostly-dummy dumper to put representers in """

        def represent_short_seq(self, data):
            data = f'[{len(data)} items]'
            return self.represent_str(data)

    @property
    def pretty(self):
        return yaml.dump(self, Dumper=self._PrettyDumper)

    def __init_subclass__(cls, /, **kwargs):
        super().__init_subclass__(**kwargs)

        representers = {
                Mapping: yaml.Dumper.represent_dict,
                Sequence: cls._PrettyDumper.represent_short_seq,
                }
        for supercls, representer in representers.items():
            if issubclass(cls, supercls):
                cls._PrettyDumper.add_representer(cls, representer)


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


def str_reverse(s):
    return s[::-1]


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

def aeval(expr, context):
    interpreter = asteval.Interpreter(symtable=context, minimal=True)
    return interpreter.eval(expr)

def divup(a, b):  # pylint: disable=invalid-name
    """ Divide A by B with integer division, rounding up instead of down."""
    # Credit to stackoverflow: http://stackoverflow.com/a/7181952/4638839
    return (a + (-a % b)) // b


def intify(x, default):  # pylint: disable=invalid-name
    """ A forgiving int() cast; returns default if typecast fails."""
    if isinstance(x, int):
        return x
    try:
        return int(x, 0)
    except (ValueError, TypeError):
        return x if default is None else default

def intify_items(dct, keys, default=None):
    for key in keys:
        if not dct[key]:  # empty string
            dct[key] = default
            continue
        dct[key] = int(dct[key], 0)

def get_subfiles(root, folder, extension):
    try:
        filenames = [filename for filename
                     in os.listdir("{}/{}".format(root, folder))
                     if filename.endswith(extension)]
        names = [os.path.splitext(filename)[0]
                 for filename in filenames]
        paths = ["{}/{}/{}".format(root, folder, filename)
                 for filename in filenames]
        return zip(names, paths)
    except FileNotFoundError:
        log.warn(f"{root}/{folder} not found, treating as empty")
        return []

def libpath(path):
    return pathjoin(libroot, path)

def libwalk(path):
    for dirname, dirs, files in os.walk(libpath(path)):
        for filename in (dirs + files):
            yield pathjoin(dirname, filename)

def load_builtins(path, extension, loader):
    path = libpath(path)
    builtins = {}
    for filename in os.listdir(path):
        base, ext = os.path.splitext(filename)
        if ext == extension:
            builtins[base] = loader(pathjoin(path, filename))
    return builtins

def writetsv(path, data, force=False, headers=None):
    mode = "w" if force else "x"
    data = list(data)
    if headers is None:
        headers = data[0].keys()
    with open(path, mode, newline='') as f:
        # FIXME: Wonder if I can auto-generate per-struct dialects that do the
        # right thing with validate() on loading, so we find out about size or
        # type mismatches right away.
        writer = csv.DictWriter(f, headers, dialect='romtool')
        writer.writeheader()
        for item in data:
            writer.writerow(item)

def readtsv(path):
    with open(path, newline='') as f:
        return (Dict(item) for item in csv.DictReader(f, dialect='romtool'))

def filesize(f):
    """ Get the size of a file """
    pos = f.tell()
    f.seek(0, 2)
    size = f.tell()
    f.seek(pos)
    return size

def unstring(stringdict, funcmap, remove_blank=False):
    out = {}
    for k, v in stringdict.items():
        if k not in funcmap:
            out[k] = v
        elif remove_blank and v == '':
            continue
        elif isinstance(v, str):
            out[k] = funcmap[k](v)
        else:
            out[k] = v
    assert len(out) == len(stringdict) or remove_blank
    return out

def bracket(s, index):
    start = s[:index]
    char = '[{}]'.format(s[index])
    end = s[index+1:]
    return start + char + end

def all_none(*args):
    return all(i is None for i in args)

def any_none(*args):
    return any(i is None for i in args)

def bytes2ba(_bytes, *args, **kwargs):
    ba = bitarray(*args, **kwargs)
    ba.frombytes(_bytes)
    return ba

def convert(dct, mapper):
    return {k: conv_map[k](v) if k in mapper else v}

def duplicates(iterable):
    return [k for k, v
            in Counter(chain(*iterables)).items()
            if v > 1]

def subregistry(cls):
    def initsub(cls, **kwargs):
        cls.__init_subclass__(**kwargs) # FIXME: not sure how to make this work
        name = cls.__name__
        if name in cls.registry:
            raise ValueError(f"duplicate definition of '{name}'")
        cls.registry[name] = cls

    cls.registry = {}
    cls.__init_subclass__ = initsub
    return cls

