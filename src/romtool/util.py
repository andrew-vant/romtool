""" Various utility functions used in romtool."""

import csv
import contextlib
import importlib.resources as resources
import io
import logging
import os
import abc
from collections import OrderedDict, Counter
from collections.abc import Mapping, MutableMapping, Sequence
from itertools import chain
from functools import lru_cache
from os.path import dirname, realpath
from os.path import join as pathjoin
from pathlib import Path
from enum import IntEnum

import yaml
import asteval
import appdirs
import jinja2
from bitarray import bitarray
from bitarray.util import bits2bytes
from itertools import tee

log = logging.getLogger(__name__)

# romtool's expected format is tab-separated values, no quoting, no
# escaping (i.e. tab literals aren't allowed)

csv.register_dialect(
        'romtool',
        delimiter='\t',
        lineterminator=os.linesep,
        quoting=csv.QUOTE_NONE,
        doublequote=False,
        quotechar=None,
        strict=True,
        )


def cache(function):
    """ Simple unbounded cache decorator

    Backport of functools.cache. Here to avoid dependency on 3.9+.
    """
    return lru_cache(maxsize=None)(function)


class CheckedDict(dict):
    """ A dictionary that warns you if you overwrite keys."""

    class KeyConflict(KeyError):
        """ Error indicating an attempt to overwrite a key """
        def __init__(self, keys):
            self.keys = [keys] if isinstance(keys, str) else keys

        def __str__(self):
            keys = ' ,'.join(self.keys)
            return f"key(s) already set: {keys}"

    def __setitem__(self, key, value):
        if key in self and value != self[key]:
            raise CheckedDict.KeyConflict(key)
        super().__setitem__(key, value)

    def update(self, other):
        bad = [k for k, v in other.items()
               if k in self and v != self[k]]
        if bad:
            raise CheckedDict.KeyConflict(bad)
        super().update(other)


class HexInt(int):
    """ An int that always prints as hex

    Suitable for printing offsets.
    """
    sz_bits: int  # for pylint

    def __new__(cls, value, sz_bits=None):
        if isinstance(value, str):
            value = int(value, 0)
        self = int.__new__(cls, value)
        self.sz_bits = sz_bits or value.bit_length() or 8
        if self.sz_bits < value.bit_length():
            msg = f"can't fit {value} in {self.sz_bits} bits"
            raise ValueError(msg)
        return self

    def __repr__(self):
        return f"{type(self).__name__}({self})"

    def __str__(self):
        """ Print self as a hex representation of bytes """
        # two digits per byte; bytes are bits/8 rounding up.
        digits = bits2bytes(self.sz_bits) * 2
        sign = '-' if self < 0 else ''
        return f'{sign}0x{abs(self):0{digits}X}'


class Offset(HexInt):
    # Need to do something canonical with this because fuck it's annoying
    # translating. Needs to track bits internally, have bytes/bits attributes,
    # something like divmod, handle arithmetic, provide useful
    # string and format methods.
    def __new__(cls, *args, bytes=None, bits=None):
        if args and (bytes or bits):
            raise ValueError("supply value or bytes/bits, not both")
        if args:
            return super().__new__(cls, *args)
        return super().__new__(cls, bytes*8+bits)

    @property
    def bytes(self):
        return self // 8

    @property
    def bits(self):
        return self % 8


class IndexInt(int):
    """ An int representing a table index

    Dumps and parses as the name of the corresponding item in a given table.
    """
    def __new__(cls, table, value):
        if not isinstance(table, Sequence):
            raise ValueError("tried to make an IndexInt referencing "
                             "something that isn't a table")
        if isinstance(value, str):
            try:
                value = int(value, 0)
            except ValueError:
                value = table.locate(value)
        self = int.__new__(cls, value)
        self.table = table
        return self

    @property
    def obj(self):
        return self.table[self]  # pylint: disable=no-member

    def __repr__(self):
        #pylint: disable=no-member
        return f"IndexInt({self.table.name} #{int(self)} ({str(self)})"

    def __str__(self):
        return self.obj.name


class RomObject(abc.ABC):
    """ Base class for rom objects that act as collections

    Defines a common interface intended to permit "do what I mean" operations
    across different types.
    """

    @abc.abstractmethod
    def lookup(self, key):
        """ Look up a sub-object within this container

        Subclass implementations should accept any sort of key that might make
        sense. e.g. field ids, field names, table indices, names to search for,
        etc. The aim is to allow nested lookups to proceed without having to
        worry about the underlying types.

        Implementations should raise LookupError if the key isn't present.
        """

class Searchable:
    """ Generator wrapper that supports lookups by name """
    _NO_MATCH = object()

    def __init__(self, iterable, searcher=None):
        self.iter = iter(iterable)
        self.searcher = searcher or self._default_search

    @staticmethod
    def _default_search(obj, key):
        NM = Searchable._NO_MATCH
        return obj == key or getattr(obj, 'name', NM) == key

    def __iter__(self):
        yield from self.iter

    def __str__(self):
        return f"{type(self).__name__}({self.iter})"

    def lookup(self, key):
        try:
            return next(item for i, item in enumerate(self)
                        if key == i or self.searcher(item, key))
        except StopIteration:
            typename = getattr(self, 'name', 'object')
            raise LookupError(key)


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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        representers = {
                Mapping: yaml.Dumper.represent_dict,
                Sequence: cls._PrettyDumper.represent_short_seq,
                }
        for supercls, representer in representers.items():
            if issubclass(cls, supercls):
                cls._PrettyDumper.add_representer(cls, representer)


class RomEnum(IntEnum):
    """ Enum variant for simpler dumping/loading """
    def __str__(self):
        return self._name_ # pylint: disable=no-member

    @classmethod
    def parse(cls, string):
        try:
            return cls[string]
        except KeyError:
            pass
        try:
            return cls(int(string, 0))
        except ValueError:
            pass
        raise ValueError(f"not a valid {cls}: {string}")


class SequenceView:
    """ View of a subset of sequence items

    Usually produced by slicing a table. Item lookups against the view are
    relative to the slice. As with dictionary views, changes to the underlying
    object are visible in the view.
    """
    def __init__(self, sequence, sl):
        self.sequence = sequence
        self.slice = sl
        self.indices = sl.indices(len(sequence))

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return type(self)(self, i)
        return self.sequence[self.indices[i]]

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            for i, v in zip(i.indices(len(self)), v):
                self[i] = v
        else:
            self.sequence[self.indices[i]] = v

def flatten_dicts(dct, _parent_keys=None):
    """ Turn nested dicts into a sequence of paths-to-values """
    if _parent_keys is None:
        _parent_keys = []
    for k, v in dct.items():
        path = _parent_keys + [k]
        if isinstance(v, Mapping):
            yield from flatten_dicts(v, path)
        else:
            yield (path, v)


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
        msg = f"Problem loading {listname} #{index} ({name}): {ex}"
        ex.args = (msg,)
        raise


def pipeline(first, *functions):
    """ Apply several functions to an object in sequence """
    for func in functions:
        first = func(first)
    return first


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

def get_subfiles(root, folder, ext=None, empty_if_missing=True):
    """ Get files under a given folder with given extension(s)

    Meant to ease collecting structures, bitfields, etc. Yields Path objects.
    `ext` may be a single string, a list of strings, or None. If it is None
    (the default), all files under `folder` will be returned. If
    empty_if_missing is True (the default), a missing folder will be produce an
    empty interable instead of FileNotFoundError.
    """
    if root is None:
        root = resources.files(__package__)
    if isinstance(root, str):
        root = Path(root)
    if isinstance(ext, str):
        ext = [ext]
    catch = FileNotFoundError if empty_if_missing else ()
    try:
        yield from (path for path
                    in root.joinpath(folder).iterdir()
                    if ext is None or path.suffix in ext)
    except catch as ex:
        yield from iter(())


def load_builtins(path, extension, loader):
    builtins = {}
    for path in get_subfiles(None, path, extension, False):
        log.debug("Loading builtin: %s", path.name)
        builtins[path.stem] = loader(path)
    return builtins


def dumptsv(target, dataset, force=False, headers=None, index=None):
    """ Dump an iterable of mappings to a tsv file

    If an `index` string is provided, a matching column will be added to the
    output to indicate the original order of the data.

    `target` may be a string, Path, or open file object.
    """
    mode = 'w' if force else 'x'
    writer = None
    desc = getattr(dataset, 'name', '')
    with flexopen(target, mode, newline='') as f:
        # FIXME: Wonder if I can auto-generate per-struct dialects that do the
        # right thing with validate() on loading, so we find out about size or
        # type mismatches right away.
        for i, item in enumerate(dataset):
            if not writer:
                headers = list(headers or item.keys())
                if index:
                    headers.append(index)
                writer = csv.DictWriter(f, headers, dialect='romtool')
                writer.writeheader()
            log.debug("Dumping %s #%s", desc, i)
            record = {index: i} if index else {}
            record.update(item.items())
            writer.writerow(record)


@contextlib.contextmanager
def flexopen(target, *args, **kwargs):
    """ 'Open' a path or file object with a unified interface

    `target` may be a string, Path object, or open file. Any additional
    arguments will be passed to the underlying open() call. Returns the opened
    file object.

    If flexopen opens a file, it will close it on exit. If passed an
    already-opened file, it will leave it open -- the assumption is that
    whoever opened it will close it when needed.

    It is safe to do 'with flexopen' to stdin/stdout; it won't close them.
    """
    if isinstance(target, io.IOBase):
        if args or kwargs:
            # This shouldn't be needed, but it will force things to break
            # noisily if someone passes incompatible arguments.
            target.reconfigure(*args, **kwargs)
        yield target
    else:
        if isinstance(target, str):
            target = Path(target)
        with target.open(*args, **kwargs) as f:
            yield f


def readtsv(infile):
    """ Read in a tsv file

    Accepts a string, Path, or open file object. File objects should be
    opened in text mode with newline=''.
    """
    with flexopen(infile, newline='') as f:
        return list(csv.DictReader(f, dialect='romtool'))


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
    return {k: mapper[k](v) if k in mapper else v
            for k, v in dct.items()}

def duplicates(iterable):
    return [k for k, v
            in Counter(chain(*iterable)).items()
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

@cache
def nointro():
    """ Get the nointro database as a dict """
    return {item['sha1']: item['name'] for item
            in readtsv(resources.files(__package__).joinpath('nointro.tsv'))}

class TSVLoader:
    """ Helper class for turning tsv rows into constructor arguments """
    def __init__(self, convmap):
        self.convmap = convmap
        # convmap should provide column names, a default value if the column
        # isn't set, and a conversion function if the column is set

    def parse(self, row):
        pass


def loadyaml(data):
    # Just so I don't have to remember the extra argument everywhere.
    # Should take anything yaml.load will take.
    return yaml.load(data, Loader=yaml.SafeLoader)


def slurp(path, *args, **kwargs):
    with flexopen(path, *args, **kwargs) as f:
        return f.read()

def chunk(seq, chunksize):
    for i in range(0, len(seq), chunksize):
        yield seq[i:i+chunksize]

def debug_structure(data, loglevel=logging.DEBUG):
    """ yamlize a data structure and log it as debug """
    for line in yaml.dump(data).splitlines():
        log.log(loglevel, line)

def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)

def roundup(n, base):
    """ Round N up to the next multiple of `base` """
    # credit: https://stackoverflow.com/a/14092788/
    return n - n % (-base)

@cache
def jinja_env():
    user_templates = Path(appdirs.user_data_dir('romtool'), 'templates')
    tpl_loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(user_templates),
        jinja2.PackageLoader('romtool'),
        ])
    return jinja2.Environment(
            loader=tpl_loader,
            extensions=['jinja2.ext.do'],
            )

def tsv2html(infile, caption=None):
    reader = csv.reader(infile, dialect='romtool')
    template = jinja_env().get_template('tsv2html.html')
    return template.render(
            caption=caption,
            headers=next(reader),
            rows=reader
            )

def jrender(_template, **kwargs):
    return jinja_env().get_template(_template).render(**kwargs)

def nodestats(node):
    """ Get some debugging statistics about an anynode node """
    childcount = lambda node: len(node.children)
    largest = max(node.descendants, key=childcount)
    return {
        str(node): {
            'height': node.height,
            'depth': node.depth,
            'children': len(node.children),
            'descendants': len(node.descendants),
            'largest child': f'{largest} ({childcount(largest)} children)',
            }
        }

class lstr:
    """ Calls a function only when its result needs to be printed """
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        return str(self.func(*self.args, **self.kwargs))
