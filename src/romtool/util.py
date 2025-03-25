""" Various utility functions used in romtool."""

import csv
import contextlib
import hashlib
import importlib.resources as resources
import io
import logging
import os
import re
from collections import OrderedDict, Counter
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from functools import lru_cache, partial
from pathlib import Path
from enum import IntEnum

import anytree
import yaml
import asteval
import appdirs
import jinja2
from bitarray import bitarray
from bitarray.util import bits2bytes
from itertools import tee

from .exceptions import MapError

log = logging.getLogger(__name__)

# romtool's expected format is tab-separated values, no quoting, no
# escaping (i.e. tab literals aren't allowed)

class TSV(csv.Dialect):
    delimiter = '\t'
    lineterminator = os.linesep
    quoting = csv.QUOTE_NONE
    doublequote = False
    quotechar=None
    strict = True
csv.register_dialect('rt_tsv', TSV)
TSVReader = partial(csv.DictReader, dialect='rt_tsv')
TSVWriter = partial(csv.DictWriter, dialect='rt_tsv')


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


class Handler(contextlib.suppress):
    """ Exception suppressor that calls a function on suppressed exceptions

    If any of the listed exceptions are raised, the handler will be called with
    the exception object as an argument. Otherwise this behaves as
    contextlib.suppress.

    To use handler functions with more than one argument, supply the additional
    arguments in advance using partial().
    """
    def __init__(self, handler, *exceptions):
        super().__init__(*exceptions)
        self.handler = handler

    def __exit__(self, extp, ex, traceback):
        suppressible = super().__exit__(extp, ex, traceback)
        if suppressible:
            self.handler(ex)
        return suppressible

    @classmethod
    def log(cls, exceptions, logger, level=logging.DEBUG, msg='%s'):
        """ Get a Handler that logs suppressed exceptions

        Supply the logger to use and an optional level and msg. The default is
        to log the object alone as DEBUG. `exceptions` may be an exception type
        or tuple of same.
        """
        if not isinstance(exceptions, tuple):
            exceptions = (exceptions,)
        handler = partial(logger.log, level, msg)
        return cls(handler, *exceptions)

    @classmethod
    def missing(cls, logger, *args, **kwargs):
        """ Get a Handler that logs missing files

        Useful when looking for a file in multiple locations. Arguments are the
        same as Handler.log, except that the exception list may be omitted.
        """
        return cls.log(FileNotFoundError, logger, *args, **kwargs)


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
    def __new__(cls, *args, bytes=None, bits=None):  # pylint:disable=redefined-builtin
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
                value = locate(table, value)
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
        return getattr(self.obj, 'name', str(int(self)))


def throw(ex, *args, **kwargs):
    """ Raise an exception from an expression """
    raise ex(*args, **kwargs)


class Locator:
    def __init__(self):
        self.locate = type(self).locate

    def __call__(self, sequence, name):
        return self.locate(sequence, name)

    @contextmanager
    def cached(self):
        """ Temporarily cache locate calls

        This is supposed to help with the abysmal slowness of resolving
        cross-references in tsv input files. I'm pretty sure this is a terrible
        idea and will bite me at some point. FIXME: test if this is still an
        issue.

        The cache will return stale results if the name of an entity changes
        between cross-references. This *shouldn't* happen during changeset
        loading, but could easily happen during other use, hence it not being
        the default behavior.
        """
        orig = self.locate
        self.locate = cache(self.locate)
        log.debug("locate() caching enabled")
        try:
            yield self
        finally:
            self.locate = orig
            log.debug("locate() caching disabled")

    @staticmethod
    def locate(sequence, name):  # pylint: disable=method-hidden
        """ Look up a sequence item by name

        Returns the index of the first item that is either a matching string, or
        has a .name attribute that is a matching string.
        """
        # TODO: Made a util function so lookups don't require all sequences to
        # have a locate() methods. Can't do it in-place because I need to
        # preserve the ability to toggle a cache in a way that will be seen by
        # other parts of the program. (which is terrible, but I don't have a
        # better way to get around the EntityList perf problem right
        # now...double check that it's still a problem.)
        try:
            return next(i for i, e in enumerate(sequence) if e.name == name)
        except AttributeError as ex:
            raise MapError(f"Tried to look up {sequence.name} by name, "
                            "but they are nameless") from ex
        except StopIteration as ex:
            seqname = getattr(sequence, 'id', 'sequence')
            raise ValueError(f"No object named {name} in {seqname}") from ex


locate = Locator()


class NodeMixin(anytree.NodeMixin):
    """ NodeMixin with expensive consistency checks disabled

    See anytree issue #206: https://github.com/c0fec0de/anytree/issues/206
    """
    _debug = False  # enables expensive consistency checks

    def __attach(self, parent):
        # pylint: disable=W0212,W0238
        if parent is not None:
            self._pre_attach(parent)
            parentchildren = parent.__children_or_empty
            assert (not self._debug
                    or not any(child is self for child in parentchildren)), \
                    "Tree is corrupt."  # pragma: no cover
            # ATOMIC START
            parentchildren.append(self)
            self.__parent = parent
            # ATOMIC END
            self._post_attach(parent)

    def __detach(self, parent):
        # pylint: disable=W0212,W0238
        if parent is not None:
            self._pre_detach(parent)
            parentchildren = parent.__children_or_empty
            assert (not self._debug
                    or any(child is self for child in parentchildren)), \
                    "Tree is corrupt."  # pragma: no cover
            # ATOMIC START
            parent.__children = [child for child in parentchildren if child is not self]
            self.__parent = None
            # ATOMIC END
            self._post_detach(parent)


class RomObject(NodeMixin):
    """ Base class for rom objects

    Defines a common interface intended to permit "do what I mean" operations
    across different types.
    """
    def __init__(self, view, parent=None):
        self.parent = parent
        self.view = view

    def lookup(self, key):
        """ Look up a sub-object within this container

        Subclass implementations should accept any sort of key that might make
        sense. e.g. field ids, field names, table indices, names to search for,
        etc. The aim is to allow nested lookups to proceed without having to
        worry about the underlying types.

        Implementations should raise LookupError if the key isn't present.
        """
        raise NotImplementedError

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
        except StopIteration as ex:
            raise LookupError(key) from ex


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
    def __init__(self, sequence, slice_=None):
        self.sequence = sequence
        self.slice = slice_ or slice(None, None, None)

    def _indices(self):
        """ Helper equivalent of slice._indices """
        return self.slice.indices(len(self.sequence))

    def _map_index(self, i):
        """ Helper that maps an index to the underlying sequence """
        return range(*self._indices())[i]

    def __len__(self):
        return len(range(*self._indices()))

    def __eq__(self, other):
        return (len(self) == len(other)
                and all(a == b for a, b in zip(self, other)))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return type(self)(self, i)
        return self.sequence[self._map_index(i)]

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            for i, v in zip(range(*i.indices(len(self))), v):
                self[i] = v
        else:
            self.sequence[self._map_index(i)] = v


@dataclass
class FormatSpecifier:
    fill: str = None
    align: str = None
    sign: str = None
    alt: bool = False
    zero_pad: bool = False
    width: int = None
    grouping_option: str = None
    precision: int = None
    type: str = None

    pattern = re.compile(
        r'^'
        r'(?:'
        # To stop a lone type char being interpeted as fill, treat fill-align
        # as a subgroup where align is required but the subgroup as a whole
        # is optional.
        r'(?:'
            r'(?P<fill>.)?'
            r'(?P<align>[<>=^])'
        r')?'
        r'(?P<sign>[+\- ])?'
        r'(?P<alt>#)?'
        r'(?P<zero_pad>0)?'
        r'(?P<width>\d+)?'
        r'(?P<grouping_option>[_\,])?'
        r'(?:\.(?P<precision>\d+))?'
        r'(?P<type>[bdoxXneEfFgG%]?)'
        r')?'
        r'$'
    )

    def __str__(self):
        fmt = ("{fill}{align}{sign}{alt}{zero_pad}{width}"
               "{grouping_option}{precision_dot}{precision}{type}")
        return fmt.format(
            fill=self.fill or '',
            align=self.align or '',
            sign=self.sign or '',
            alt='#' if self.alt else '',
            zero_pad='0' if self.zero_pad else '',
            width=self.width or '',
            grouping_option=self.grouping_option or '',
            precision_dot='.' if self.precision is not None else '',
            precision=self.precision or '',
            type=self.type or '',
        )

    @classmethod
    def parse(cls, spec):
        match = cls.pattern.match(spec)
        if not match:
            raise ValueError("Invalid format specifier")
        groups = match.groupdict()
        return cls(
            fill=groups['fill'],
            align=groups['align'],
            sign=groups['sign'],
            alt=bool(groups['alt']),
            zero_pad=bool(groups['zero_pad']),
            width=int(groups['width']) if groups['width'] else None,
            grouping_option=groups['grouping_option'],
            precision=int(groups['precision']) if groups['precision'] else None,
            type=groups['type'],
        )

class ChainView(Sequence):
    """ Variant of chain() that is a real indexable sequence

    Item lookups are forwarded to the corresponding underlying parent sequence
    in the order they were specified. So e.g.
    """
    def __init__(self, *parents):
        self.parents = parents

    def __len__(self):
        return sum(len(p) for p in self.parents)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        for parent in self.parents:
            if i < len(parent):
                return parent[i]
            i -= len(parent)
        raise IndexError(f"{i} out of range")

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            SequenceView(self)[i] = v
        else:
            for parent in self.parents:
                if i < len(parent):
                    parent[i] = v
                    return
                i -= len(parent)
        raise IndexError(f"{i} out of range")


def seqview(sequence, _slice):
    # will something like this work?
    return partial(sequence.__getitem__, _slice)


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
        log.debug("%s (treating as empty)", ex)
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
                writer = TSVWriter(f, headers)
                writer.writeheader()
            log.debug("Dumping %s #%s", desc, i)
            record = {index: i} if index else {}
            record.update(item.items())
            writer.writerow(record)


@contextlib.contextmanager
def flexopen(target, mode=None, /, *args, **kwargs):
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
        if kwargs:
            # This shouldn't be needed, but it will force things to break
            # noisily if someone passes incompatible arguments.
            target.reconfigure(*args, **kwargs)
        if mode and mode != target.mode:
            raise ValueError(f"tried to open {target} with mode '{mode}', but "
                             f"it is already open in mode '{target.mode}'")
        yield target
    else:
        if isinstance(target, str):
            target = Path(target)
        mode = mode or 'r'
        with target.open(mode, *args, **kwargs) as f:  # pylint: disable=unspecified-encoding
            yield f


def readtsv(infile):
    """ Read in a tsv file

    Accepts a string, Path, or open file object. File objects should be
    opened in text mode with newline=''.
    """
    with flexopen(infile, newline='') as f:
        return list(TSVReader(f))


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


def sha1(file):
    """ Get sha1 hash of a file as a hexdigest

    Accepts a string, path-like object, or open binary file.
    """
    filehash = hashlib.sha1()
    with flexopen(file, 'rb') as f:
        prev = f.tell()
        f.seek(0)
        for block in iter(partial(f.read, 2**20), b''):
            filehash.update(block)
        f.seek(prev)
    return filehash.hexdigest()


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

def safe_iter(sequence, errstr="[[ {ex} ]]", extypes=(Exception,)):
    """ Handle exceptions while iterating over a sequence

    This mainly exists to be used as a jinja filter when generating
    documentation, though in principle it will work elsewhere.
    """
    extypes = extypes or (Exception,)
    for i in range(len(sequence)):
        try:
            yield sequence[i]
        except extypes as ex:
            log.warning(ex)
            yield errstr.format(ex=ex)

@cache
def jinja_env():
    user_templates = Path(appdirs.user_data_dir('romtool'), 'templates')
    tpl_loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(user_templates),
        jinja2.PackageLoader('romtool'),
        ])
    env = jinja2.Environment(
            loader=tpl_loader,
            extensions=['jinja2.ext.do'],
            finalize=lambda obj: "" if obj is None else obj,
            autoescape=jinja2.select_autoescape(["html", "htm", "xml", "jinja"])
            )
    env.filters["safe_iter"] = safe_iter
    return env

def tsv2html(infile, caption=None):
    reader = csv.reader(infile, dialect='rt_tsv')
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
