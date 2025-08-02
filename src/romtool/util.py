""" Various utility functions used in romtool."""

import contextlib
import csv
import hashlib
import io
import logging
import os
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from functools import cache, partial
from importlib import resources
from itertools import chain, tee
from pathlib import Path

import anytree
import yaml
from bitarray import bitarray
from bitarray.util import bits2bytes

from .exceptions import MapError

log = logging.getLogger(__name__)
loadyaml = partial(yaml.load, Loader=yaml.SafeLoader)
ichain = chain.from_iterable


class TSV(csv.Dialect):  # pylint: disable=too-few-public-methods
    """ Dialect for tab-separated values.

    Romtool's expected format is TSV, no quoting, no escaping (i.e. tab
    literals aren't allowed).
    """
    delimiter = '\t'
    lineterminator = os.linesep
    quoting = csv.QUOTE_NONE
    doublequote = False
    quotechar = None
    strict = True


csv.register_dialect('rt_tsv', TSV)
TSVReader = partial(csv.DictReader, dialect='rt_tsv')
TSVWriter = partial(csv.DictWriter, dialect='rt_tsv')


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

    Suitable for printing offsets. Takes a size specifier intended to ensure
    that the printed result is as wide as the underlying data field (e.g.
    w/zero padding). This is necessary when the code printing the value
    doesn't know anything about the field it came from.

    I'm sure there's a better way to do this.
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
    """ An HexInt customized for working with offsets.

   Not currently used. Need to do something canonical with this because fuck
   it's annoying translating. Needs to track bits internally, have bytes/bits
   attributes, something like divmod, handle arithmetic, provide useful
   string and format methods.
   """
    def __new__(cls, *args, bytes=None, bits=None):  # pylint:disable=redefined-builtin
        if args and (bytes or bits):
            raise ValueError("supply value or bytes/bits, not both")
        if args:
            return super().__new__(cls, *args)
        return super().__new__(cls, bytes*8+bits)

    @property
    def bytes(self):
        """ Get the offset in bytes, rounded down. """
        return self // 8

    @property
    def bits(self):
        """ Get the remainder of the offset in bits. """
        return self % 8


class IndexInt(int):
    """ An int representing a table index

    Dumps and parses as the name of the corresponding item in a given table.
    -1 converts as the empty string, to accomodate cases where 0 means
    'nothing'.
    """
    def __new__(cls, table, value):
        if not isinstance(table, Sequence):
            raise ValueError("tried to make an IndexInt referencing "
                             "something that isn't a table")
        if isinstance(value, str):
            try:
                value = int(value, 0) if value else -1
            except ValueError:
                value = locate(table, value)
        self = int.__new__(cls, value)
        self.table = table
        return self

    @property
    def obj(self):
        """ Look up the item with this index in the underlying table. """
        return None if self < 0 else self.table[self]  # pylint: disable=no-member

    def __repr__(self):
        # pylint: disable=no-member
        return f"IndexInt({self.table.name} #{int(self)} ({str(self)})"

    def __str__(self):
        if self < 0:
            return ''
        try:
            return getattr(self.obj, 'name', str(int(self)))
        except IndexError as ex:
            log.debug("%s #%s does not exist (%s)",
                      self.table.name, int(self), ex)
        return str(int(self))


def throw(ex, *args, **kwargs):
    """ Raise an exception from an expression """
    raise ex(*args, **kwargs)


class Locator:
    """ Helper for crossref resolution.

    Resolving objects by name can get very expensive with sufficiently
    pessimal rom formats. Locator provides both a helper method to look up
    objects by name, and a context manager that temporarily caches the
    results.

    This is almost certainly the wrong way to do this, but it works for now.
    """

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

        Returns the index of the first item that is either a matching string,
        or has a .name attribute that is a matching string. If there is no
        name attribute, also check if the name is itself an integer index.
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
            try:
                return int(name, 0)
            except ValueError:
                raise MapError(f"Tried to look up {sequence.name} by name, "
                               f"but they are nameless") from ex
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
                    or not any(child is self for child in parentchildren)
                    ), "Tree is corrupt."  # pragma: no cover
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
                    or any(child is self for child in parentchildren)
                    ), "Tree is corrupt."  # pragma: no cover
            # ATOMIC START
            parent.__children = [child for child in parentchildren
                                 if child is not self]
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
    """ Generator wrapper that supports lookups by name. """
    # FIXME: hate the whole call chain this is involved in.
    _NO_MATCH = object()

    def __init__(self, iterable, searcher=None):
        self.iter = iter(iterable)
        self.searcher = searcher or self._default_search

    @staticmethod
    def _default_search(obj, key):
        # Some attr lookups are expensive, so short-circuit if possible
        nm = Searchable._NO_MATCH
        return obj == key or getattr(obj, 'name', nm) == key

    def __iter__(self):
        yield from self.iter

    def __str__(self):
        return f"{type(self).__name__}({self.iter})"

    def lookup(self, key):
        """ Get the first item in the iterable with the matching key.

        The key may be an index, in which case the indexed item is returned.
        Otherwise returns the first item for which `searcher(item, key)`
        is true. By default searches for the first item that is equal to the
        lookup key or the first item that has a name equal to the lookup key.
        """
        try:
            return next(item for i, item in enumerate(self)
                        if key == i or self.searcher(item, key))
        except StopIteration as ex:
            raise LookupError(key) from ex


class RomEnum(IntEnum):
    """ Enum variant for simpler dumping/loading """
    def __str__(self):
        return self._name_  # pylint: disable=no-member

    @classmethod
    def parse(cls, string):
        """ Attempt to parse an enum string.

        If the string names an enum value, returns that value. If it is a
        valid integer, return that int. Any other string raises an exception.
        """
        # FIXME: This is almost certainly the wrong way to do this. I think
        # I'm supposed to override _missing_ and then do RomEnum[string].
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

    def __setitem__(self, item, value):
        if isinstance(item, slice):
            for i, v in zip(range(*item.indices(len(self))), value):
                self[i] = v
        else:
            self.sequence[self._map_index(i)] = v


@dataclass
class FormatSpecifier:  # pylint: disable=too-many-instance-attributes
    """ Parser for the standard format-specification mini-language (FSML).

    Intended as an aid to classes that want to accept a similar format spec,
    but for whatever reason can't just forward to another type.
    """
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
        """ Parse an FSML spec into a FormatSpecifier object. """
        match = cls.pattern.match(spec)
        if not match:
            raise ValueError("Invalid format specifier")
        gd = match.groupdict()
        return cls(
            fill=gd['fill'],
            align=gd['align'],
            sign=gd['sign'],
            alt=bool(gd['alt']),
            zero_pad=bool(gd['zero_pad']),
            width=int(gd['width']) if gd['width'] else None,
            grouping_option=gd['grouping_option'],
            precision=int(gd['precision']) if gd['precision'] else None,
            type=gd['type'],
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


def load_builtins(folder, extension, loader):
    """ Load packaged data files with an appropriate loader.

    Looks in the given subfolder within the romtool package directory for
    files with the given extension, and passes their paths as the sole
    argument to the specified loader. Returns a mapping of each file's path
    stem to the object loaded from it.
    """
    builtins = {}
    for path in get_subfiles(None, folder, extension, False):
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


def bytes2ba(_bytes, *args, **kwargs):
    """ Convert a bytes object to a bitarray and return it.

    The bitarray API doesn't have a good way to do this within an expression.
    """
    ba = bitarray(*args, **kwargs)
    ba.frombytes(_bytes)
    return ba


@cache
def nointro():
    """ Get the nointro database as a dict """
    return {item['sha1']: item['name'] for item
            in readtsv(resources.files(__package__).joinpath('nointro.tsv'))}


def slurp(path, *args, **kwargs):
    """ Read the contents of a file.

    Trivial helper. A fair number of loading functions expect to receive a
    path rather than an open file; this provides a compatible interface, e.g.
    for function tables.
    """
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
    """ Iterate over chunks of a sequence.

    The yielded chunks are produced by slicing; thus they may be copies,
    depending on the underlying type.
    """
    for i in range(0, len(seq), chunksize):
        yield seq[i:i+chunksize]


def debug_structure(data, loglevel=logging.DEBUG):
    """ yamlize a data structure and log it as debug """
    for line in yaml.dump(data).splitlines():
        log.log(loglevel, line)


def pairwise(iterable):
    """ Iterate over consecutive pairs in an iterable. """
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
    sequence = iter(sequence)
    while True:
        try:
            yield next(sequence)
        except StopIteration:
            break
        except extypes as ex:
            log.warning(ex)
            yield errstr.format(ex=ex)


def nodestats(node):
    """ Get some debugging statistics about an anynode node """
    largest = max(node.descendants, key=lambda node: len(node.children))
    return {
        str(node): {
            'height': node.height,
            'depth': node.depth,
            'children': len(node.children),
            'descendants': len(node.descendants),
            'largest child': f'{largest} ({len(largest.children)} children)',
            }
        }


class lstr:  # pylint: disable=invalid-name,too-few-public-methods
    """ Calls a function only when its result needs to be printed """
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        return str(self.func(*self.args, **self.kwargs))
