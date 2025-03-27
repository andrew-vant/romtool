""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import dataclasses as dc
import logging
from collections import UserList, ChainMap
from collections.abc import Mapping, Sequence, MutableMapping
from itertools import chain, combinations, islice
from functools import partial, cached_property
from os.path import basename, splitext
from io import BytesIO
from abc import ABC
from string import ascii_letters

from addict import Dict
from asteval import Interpreter

from .field import Field, FieldExpr
from . import util
from .util import cache, RomObject, SequenceView, CheckedDict, HexInt
from .io import Unit
from .exceptions import RomtoolError, MapError


log = logging.getLogger(__name__)


class Entity(MutableMapping):
    """ Wrapper for corresponding objects in parallel tables

    Attribute and key operations on an Entity will be forwarded to the `i`th
    element of each underlying table until one returns successfully. For tables
    that return a primitive value, the lookup will be checked against the
    table's name.
    """
    # pylint: disable=no-member
    def __init_subclass__(cls, tables, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._all_fields = []
        cls._tables_by_attr = CheckedDict()
        cls._tables_by_name = CheckedDict()
        cls._keys_by_table = {}
        for table in tables:
            cls._keys_by_table[table] = []
            fields = table.struct.fields if table.struct else [table.field]
            for field in fields:
                cls._all_fields.append(field)
                cls._tables_by_attr[field.id] = table
                cls._tables_by_name[field.name] = table
                cls._keys_by_table[table].append(field.name)
                prop = property(partial(cls._getattr, attr=field.id),
                                partial(cls._setattr, attr=field.id))
                if hasattr(cls, field.id):
                    raise MapError(f"{cls.__name__}.{field.id} shadows a "
                                   f"built-in attribute")
                setattr(cls, field.id, prop)
        cls._keys = [f.name for f in sorted(cls._all_fields)]

    @classmethod
    def keys(cls):  # pylint: disable=arguments-differ
        yield from cls._keys

    @classmethod
    def define(cls, name, tables):
        """ Define an entity type that proxies to the given tables. """
        return type(name, (cls,), {}, tables=tables)

    def __init__(self, index):
        super().__setattr__('_i', index)

    def __str__(self):
        tnm = type(self).__name__
        inm = getattr(self, 'name', 'nameless')
        return f'{tnm} #{self._i} ({inm})'

    def __len__(self):
        return len(type(self)._keys)

    def __repr__(self):
        tnm = type(self).__name__
        return f'{tnm}({self._i})'

    def __iter__(self):
        yield from type(self)._keys

    def __getitem__(self, key):
        try:
            item = self._tables_by_name[key][self._i]
        except ValueError as ex:
            raise KeyError from ex
        return item if not isinstance(item, Structure) else item[key]

    def __setitem__(self, key, value):
        table = self._tables_by_name[key]
        if table.struct:
            table[self._i][key] = value
        else:
            table[self._i] = value

    def __delitem__(self, key):
        raise NotImplementedError("Can't delete entity fields")

    # Not called directly; init_subclass partials these to produce attribute
    # descriptors.
    def _getattr(self, *, attr):
        item = self._tables_by_attr[attr][self._i]
        return item if not isinstance(item, Structure) else getattr(item, attr)

    def _setattr(self, value, *, attr):
        table = self._tables_by_attr[attr]
        if table.struct:
            setattr(table[self._i], attr, value)
        else:
            table[self._i] = value

    def __setattr__(self, attr, value):
        if attr not in self._tables_by_attr:
            raise AttributeError(attr)
        super().__setattr__(attr, value)

    def update(self, other=(), /, **kwargs):
        """ Update this entity from a dictionary-like object

        Repeated setitem calls can get expensive. This provides a more
        performant alternative. The input dictionary should be keyed by field
        name. "extra" keys are ignored.
        """
        # The MutableMapping interface expects us to handle key-value pairs
        # and kwargs, although we haven't had a need for it yet.
        if not isinstance(other, Mapping):
            other = dict(other)
        other = ChainMap(other, kwargs)

        # Table item lookups are where most of the cost seems to be, so let's
        # see if we can limit it to once per table
        for table, keys in self._keys_by_table.items():
            try:
                item = table[self._i]
            except ValueError as ex:
                log.warning(f"can't set %s[%s]{keys}  ({ex})",
                            table.id, self._i)
                continue
            if isinstance(item, Structure):
                for k in keys:
                    item[k] = other[k]
            else:
                assert len(keys) == 1
                table[self._i] = other[keys[0]]

    def items(self):
        """ Get the field names and values in this entity

        Repeated entity key lookups can get expensive. This provides a more
        performant alternative; the underlying table lookups are only done
        once.
        """
        # FIXME: pretty sure something unexpected will happen if the update
        # includes a changed table-index entry.
        for table, keys in self._keys_by_table.items():
            try:
                item = table[self._i]
            except ValueError as ex:
                log.warning(f"can't get %s[%s]{keys}  ({ex})",
                            table.id, self._i)
                continue
            if isinstance(item, Structure):
                for k in keys:
                    yield (k, item[k])
            else:
                assert len(keys) == 1
                yield (keys[0], item)


class EntityList(Sequence):
    """ Wrapper for parallel tables

    Lookups on an EntityList return an Entity wrapping corresponding items from
    the underlying tables.
    """

    def __init__(self, name, tables):
        lengths = set(len(t) for t in tables)
        if not name:
            raise ValueError(f"Tried to create an EntityList with no name "
                             f"from tables: {', '.join(tables)}")
        if len(lengths) == 0:
            raise ValueError(f"Tried to create EntityList '{name}' "
                             f"with no underlying tables")
        if len(lengths) != 1:
            raise ValueError(f"Tables making up an EntityList must have "
                             f"equal lengths {lengths}")
        self.name = name
        self.etype = Entity.define(name, tables)
        self._length = lengths.pop()

    def __getitem__(self, i):
        if i >= len(self):
            raise IndexError(f"i >= {len(self)}")
        return self.etype(i)

    def __setitem__(self, i, v):
        self[i].update(v)

    def __len__(self):
        return self._length


class Structure(Mapping, RomObject):
    """ A structure in the ROM."""
    fields = UserList([])  # provided by subclasses

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls.fields = UserList(cls.fields)
        cls.fields.byname = {f.name: f for f in cls.fields}
        cls.fields.byid = {f.id: f for f in cls.fields}
        cls.fields.sorted = sorted(cls.fields)

    @cache
    def __new__(cls, *_, **__):
        return super().__new__(cls)

    def __getitem__(self, key):
        return self.fields.byname[key].__get__(self)

    def __setitem__(self, key, value):
        self.fields.byname[key].__set__(self, value)

    def __eq__(self, other):
        return object.__eq__(self, other)

    def __hash__(self):
        return object.__hash__(self)

    def lookup(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            pass
        try:
            return self[key]
        except KeyError:
            pass
        raise LookupError(f"Couldn't find {key} in {self}")

    @property
    def size(self):
        sz_nm = super().size
        sz_struct = sum(field.size.eval(self) * field.unit
                        for field in self.fields)
        log.warning("this method was removed because it shadowed a "
                    "NodeMixin one. As far as I know it's unused for other "
                    "purposes. Returning nodemixin size %s; if you expected "
                    "structure size %s, there's a bug here.",
                    sz_nm, sz_struct)

    @classmethod
    def attrs(cls):
        """ Get an iterator over this structure's field IDs. """
        return iter(cls.fields.byid)

    def __iter__(self):
        # Keys are technically unordered, but in many places it's very
        # convenient for the name to come 'first'.
        # FIXME: Causes issues with some subclasses, e.g. bitfields, where
        # iteration order matters for purposes of parsing. Consider making this
        # a separate iterator, perhaps part of keys().
        return (f.name for f in sorted(self.fields))

    def __len__(self):
        return len(self.fields)

    def _debug(self):
        return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                       for field in self.fields)

    def __format__(self, spec):
        if spec == 'byid':
            return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                           for field in self.fields)
        if spec == 'byname':
            return ''.join(f'{field.name}: {self[field.name]}\n'
                           for field in self.fields)
        return super().__format__(spec)

    def __str__(self):
        cls = type(self).__name__
        name = getattr(self, 'name', 'nameless')
        os_bytes, rm_bits = self.view.os_bytemod
        return f'{cls}@{os_bytes}+{rm_bits} ({name})'

    def __repr__(self):
        tpnm = type(self).__name__

        offset_bitlen = len(self.view.root).bit_length()
        byte_offset = util.HexInt(self.view.abs_start // 8, offset_bitlen)
        bit_remainder = self.view.abs_start % 8
        offset = str(byte_offset)
        if bit_remainder:
            offset += f"%{bit_remainder}"

        out = f"{tpnm}@{offset}"
        if hasattr(self, 'name'):
            name = self.name[:16]
            if len(self.name) > 16:
                name += '..'
            out += f" ({name})"
        return f"<{out}>"

    @classmethod
    def define(cls, name, fields):
        """ Define a type of structure from a list of Fields """
        attrs = {f.id: f for f in fields}
        names = [f.name for f in attrs.values()]
        for identifier in chain(attrs, names):
            if hasattr(cls, identifier):
                msg = f"{name}.{identifier} shadows a built-in attribute"
                raise ValueError(msg)

        for a, b in combinations(fields, 2):
            dupes = set(a.identifiers) & set(b.identifiers)
            if dupes:
                msg = f"Duplicate identifier(s) in {name} spec: {dupes}"
                raise ValueError(msg)

        bases = (cls,)
        attrs['fields'] = list(attrs.values())
        return type(name, bases, attrs)

    @classmethod
    def define_from_tsv(cls, path, extra_fieldtypes=None):
        """ Define a structure type from a TSV file path. """
        name = splitext(basename(path))[0]
        rows = util.readtsv(path)
        return cls.define_from_rows(name, rows, extra_fieldtypes)

    @classmethod
    def define_from_rows(cls, name, rows, extra_fieldtypes=None):
        """ Define a structure type from the rows in a TSV file. """
        fields = []
        for row in rows:
            try:
                field = Field.from_tsv_row(row, extra_fieldtypes)
            except MapError as ex:
                ex.source = f'{name}.{ex.source}' if ex.source else name
                raise
            fields.append(field)
        return cls.define(name, fields)

    def copy(self, other):
        """ Copy all attributes from one struct to another"""
        for k, v in self.items():
            if isinstance(v, Mapping):
                v.copy(other[k])
            else:
                other[k] = v


class BitField(Structure):
    """ A bitfield.

    Bitfields organize several bits into a block, usually one byte in size,
    where each bit has a different meaning. Usually they are flags of some
    sort.
    """
    def __init_subclass__(cls):
        super().__init_subclass__()
        for f in cls.fields:
            if f.display not in list(ascii_letters):
                raise ValueError(f"{cls.__name__}.{f.id}: "
                                 f"display spec must be a letter")
        cls._flags = ''.join(f.display.lower() for f in cls.fields)

    def __str__(self):
        # FIXME: I am not sure natural-style should be the default
        return format(self, '#')

    def __iter__(self):
        return (f.name for f in self.fields)

    def __repr__(self):
        tpnm = type(self).__name__
        offset = str(util.HexInt(self.view.abs_start,
                                 len(self.view.root).bit_length()))
        flags = format(self)
        return f"<{tpnm}@{offset} ({flags})>"

    def __format__(self, spec):
        """ Format the bitfield as a string

        The default format ("flag style") treats the bitfield as a series of
        flags, and returns a string with one character per flag; uppercase if
        the flag is set, lowercase if not. The letters to use are taken from
        the bit's 'display' attribute. They appear in the same order that
        they were defined.

        The 'natural style' or 'alternate format' (spec string: '#', to match
        stdlib) tries to be more human-readable where practical. If no bits
        are set, it returns the empty string, and if only one bit is set, it
        returns the name of that bit. Otherwise it falls back to the
        flag-style format.
        """
        return (self._format_natural() if spec == '#'
                else self._format_flags())

    def _format_flags(self):
        """ Implementation of flag-style format """
        return ''.join(field.display.upper() if self[field.name]
                       else field.display.lower()
                       for field in self.fields)

    def _format_natural(self):
        """ Implementation of natural-style format """
        ct_bits = sum(self.view)
        return ('' if not ct_bits
                else self._format_flags() if ct_bits > 1
                else next(k for k, v in self.items() if v))

    def parse(self, s):
        """ Update this bitfield from a string representation.

        For the allowed representations, see __format__.
        """
        if not s:
            self.view.uint = 0
        elif s in self:
            self.view.uint = 0
            self[s] = 1
        elif len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        elif s.lower() != self._flags:
            raise ValueError("String letters don't match field")
        else:
            for field, letter in zip(self.fields, s):
                self[field.name] = letter.isupper()


@dc.dataclass
class TableSpec:  # pylint: disable=R0902,R0903  # (unneeded on newer pylints?)
    """ Table specification

    Describes the format and location of a data table.
    """
    id: str
    type: str
    fid: str = None
    name: str = None
    iname: str = None
    set: str = None
    units: Unit = Unit.bytes
    count: int = None
    offset: int = 0
    stride: int = None
    size: int = None
    index: str = None
    display: str = None
    cls: str = ''
    comment: str = ''

    def __post_init__(self):
        self.fid = self.fid or self.id
        self.iname = self.iname or self.name
        self.size = self.size or self.stride
        if self.type in ['str', 'strz'] and not self.display:
            raise MapError(f"Map bug in {self.id} array: "
                           f"'display' is required for string types")

    @classmethod
    def from_tsv_row(cls, row):
        """ Define a spec from a row in a TSV file. """
        kwargs = Dict(((k, v) for k, v in row.items() if v))
        kwargs.offset = HexInt(kwargs.offset)
        kwargs.count = int(kwargs.count, 0)
        kwargs.stride = int(kwargs.stride, 0) if kwargs.stride else None
        kwargs.size = int(kwargs.size, 0) if kwargs.size else None
        return cls(**kwargs)


class Table(Sequence, RomObject, ABC):
    """ A ROM data table """
    def __init__(self, view, parent, spec, index=None):
        """ Create a table

        parent: The parent object (usually a Rom)
        view:   The reference view (usually Rom.data)
        spec:   The table spec
        index:  a list of offsets within the view
        """
        super().__init__(view, parent)
        self.spec = spec
        # FIXME: why doesn't this break when creating a Strings?
        self._index = index or [i*(spec.stride or spec.size)
                                for i in range(spec.count)]
        # These are useful enough that I might as well snap them here
        self.id = self.spec.id
        self.name = self.spec.name

    def __len__(self):
        # I've run into tables with more entries than indices. Use the
        # latter, since you can't look up anything past that anyway.
        return len(self._index)

    def __repr__(self):
        cls = type(self).__name__
        tp = self.spec.type
        ct = len(self)
        os = self.spec.offset
        return f'<{cls}({tp}*{ct}@{os})>'

    def __str__(self):
        # I would like to print the actual contents rather than the name
        # location, but the contents can't be guaranteed valid, e.g. encoding
        # errors in a string list would make str() on the list itself barf.
        name = self.spec.name
        tp = self.spec.type
        ct = len(self)
        os = self.spec.offset
        return f'{name} ({tp}*{ct}@{os})'

    def __iter__(self):
        # IndexError can get raised from downstack, which the Sequence
        # implementation of __iter__ interprets as the end of the table. This
        # version lets it propagate.
        for i in range(len(self)):
            yield self[i]

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        if i >= len(self):
            raise IndexError(f"index out of range ({i} >= {len(self)})")
        if self.struct:
            return self.struct(self.viewof(i), self)
        item = RomObject(self.viewof(i), self)
        return self.field.__get__(item)

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            indices = list(range(i.start, i.stop, i.step))
            if len(indices) != len(v):
                msg = "mismatched slice length; {len(indices)} != {len(v)}"
                raise ValueError(msg)
            for idx, value in zip(range(i.start, i.stop, i.step), v):
                self[idx] = value
        elif self.struct:
            self[i].copy(v)
        else:
            item = RomObject(self.viewof(i), self)
            self.field.__set__(item, v)

    # Do not like these digging into foreign internals
    @property
    def struct(self):
        """ Get the structure class of items in this list """
        return self.root.map.structs.get(self.spec.type, None)

    @property
    def field(self):
        """ Get the field class for items in this list """
        spec = self.spec
        return self.root.map.handlers[spec.type](
                id=spec.fid, name=spec.iname, type=spec.type,
                offset=FieldExpr('0'), size=FieldExpr(str(spec.size)),
                display=spec.display
                )

    def viewof(self, i):
        """ Get a view of a given item in the list

        Called by the default setitem/getitem implementations. Subclasses
        should override either this or setitem/getitem.
        """
        os_self = self.spec.offset
        os_item = self._index[i]
        start = os_self + os_item
        end = (start + self.spec.size) if self.spec.size else None
        units = self.spec.units
        try:
            return self.view[start:end:units]
        except IndexError as ex:
            msg = (f"bad offset for {self.name} #{i}: "
                   f"{os_self:#0x}+{os_item:#0x}")
            raise ValueError(msg) from ex

    def update(self, mapping):
        """ Update the list from an index->item mapping

        The default implementation does the obvious thing of iterating over
        the mapping keys and updating the corresponding item. It exists
        mainly to be overridden by subclasses for which repeated __setitem__
        calls are expensive, e.g. Strings.
        """
        for i, v in mapping.items():
            self[i] = v

    def lookup(self, key):
        """ Get the first item in self with a given name """
        try:
            return next(item for item in self if item.name == key)
        except AttributeError as ex:
            raise AttributeError(f"Tried to look up {self.spec.type} by name, "
                                  "but they are nameless") from ex
        except StopIteration as ex:
            raise LookupError(f"No object with name: {key}") from ex


class Index(Sequence):
    """ A dynamic table index

    Used when table item offsets require a calculation more complex than just
    `offset + stride * i`. The supplied expression is evaluated when looking
    up items. Its available symbols are everything in `symtable`, plus the
    variable `i` for the item being looked up. Alternately, the expression
    may be a key in the symtable; in that case it is assumed to be a
    reference to another table, lookups will be forwarded, and [i] need not
    be included in the expression.
    """
    def __init__(self, expr, symtable, length):
        self.expr = expr
        self.length = length
        self.symtable = symtable or {}
        self.eval = Interpreter({}, minimal=True)

    def __len__(self):
        return self.length

    def __str__(self):
        return str(self.expr)

    def __repr__(self):
        return (f"{type(self)}"
                f"({self.expr!r}, {self.length!r}, {self.symtable!r})")

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        if i >= len(self):
            raise IndexError(f"{i} > {len(self)}")
        if self.expr in self.symtable:  # skip expensive eval if we can
            return self.symtable[self.expr][i]
        self.eval.symtable = ChainMap({'i': i}, self.symtable)
        result = self.eval(self.expr, show_errors=False)
        errs = '; '.join(str(err) for err in self.eval.error or [])
        if errs:
            raise RomtoolError(f"error(s) evaluating index: {self} -> {errs}")
        return result


class Strings(Table):  # more generic type: Series?
    """ A sequence of concatenated, terminated strings.

    Used for tables of terminated strings that have no index, where the
    rom finds string N by scanning the entire table.

    String DBs handle the size and stride parameters a bit differently than
    regular tables. `stride` is the maximum size of any individual string.
    `size` is the maximum size of the entire DB. These are checked when
    overwriting entries.
    """
    @cached_property
    def codec(self):
        """ The character encoding for strings in this table. """
        return self.root.map.ttables[self.spec.display].clean

    def __iter__(self):
        view = self.view[self.spec.offset::self.spec.units]
        yield from islice(self.codec.read_from(view.bytes), len(self))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        return next(islice(self, i, None))

    def __setitem__(self, i, v):
        # changing the length of any single item requires rewriting all
        # subsequent items, because ugh.
        if isinstance(i, slice):
            # This should set multiple strings at once, useful to avoid
            # repeated iteration when updating the whole list. Alternately
            # maybe convert a single i to a slice and treat slice as the
            # default?
            raise NotImplementedError
        self.update({i: v})

    def update(self, mapping):
        """ Update all items of self that are in mapping

        The underlying data of a Strings table only supports sequential I/O.
        Random access is very slow, as finding item N requires reading all
        previous items, and writes must additionally rewrite all subsequent
        items. This override of update() batches multiple read-writes such
        that the underlying data need only be read or written once.
        """
        # FIXME: doesn't interact well with entitylist updates; it still ends
        # up re-reading the list for each item, though it doesn't reapply the
        # changes each time. I am not sure that can be escaped even in
        # principle, though, e.g. where changes to item N are depended on by
        # N+1.
        spec = self.spec
        log.debug("updating string table %s", spec.id)
        last = max(mapping)
        out = BytesIO()
        safe_length = 0  # original bytecount
        changed = False
        view = self.view[self.spec.offset::self.spec.units]
        reader = self.codec.read_from(view.bytes, with_encoding=True)
        for i, (old, oldbytes) in enumerate(islice(reader, len(self))):
            if i > last and not changed:
                return  # skip further decoding, this is a no-op
            safe_length += len(oldbytes)
            new = mapping.get(i, old)
            if new == old:
                # Don't re-encode, it can make no-op 'changes'
                log.debug("no change: %s[%s]: '%s' -> '%s' (%s)",
                          spec.id, i, old, new, oldbytes.hex())
                out.write(oldbytes)
            else:
                log.debug("changed %s[%s]: '%s' -> '%s'", spec.id, i, old, new)
                out.write(self.codec.encode(new)[0])
                changed = True
        out = out.getvalue()
        # Check for potential overrun screws
        overrun = len(out) - safe_length
        if overrun > 0:
            start = spec.offset + safe_length
            end = start + overrun
            overlap = self.view[start:end:spec.units].bytes.hex().upper()
            if len(overlap) > 32:
                overlap = overlap[:32] + '[...]'
            log.warning(f"updated %s table extends %s bytes beyond the "
                        f"original, overwriting this data: {overlap}",
                        spec.id, len(out)-safe_length)
        self.view[spec.offset:spec.offset+len(out):spec.units].bytes = out
