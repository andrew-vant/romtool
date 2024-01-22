""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import dataclasses as dc
import logging
from collections import UserList
from collections.abc import Mapping, Sequence, MutableMapping
from itertools import chain, combinations, groupby
from functools import partial
from contextlib import contextmanager
from os.path import basename, splitext
from io import BytesIO
from abc import ABC
from string import ascii_letters

import yaml
from addict import Dict
from asteval import Interpreter

from .field import Field, StructField, FieldExpr
from . import util
from .util import cache, locate, RomObject, SequenceView, CheckedDict, HexInt
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
            fields = table._struct.fields if table._struct else [table._field]
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
    def define(cls, name, tables):
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
        item = self._tables_by_name[key][self._i]
        return item if not isinstance(item, Structure) else item[key]

    def __setitem__(self, key, value):
        table = self._tables_by_name[key]
        if table._struct:
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
        if table._struct:
            setattr(table[self._i], attr, value)
        else:
            table[self._i] = value

    def __setattr__(self, attr, value):
        if attr not in self._tables_by_attr:
            raise AttributeError(attr)
        super().__setattr__(attr, value)

    def update(self, other):
        """ Update this entity from a dictionary-like object

        Repeated setitem calls can get expensive. This provides a more
        performant alternative. The input dictionary should be keyed by field
        name. "extra" keys are ignored.
        """
        # Table item lookups are where most of the cost seems to be, so let's
        # see if we can limit it to once per table
        for table, keys in self._keys_by_table.items():
            try:
                item = table[self._i]
            except IndexError as ex:
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
            except IndexError as ex:
                log.warning(f"can't get %s[%s]{keys}  ({ex})",
                            table.id, self._i)
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
            raise ValueError(f"Tried to create EntityList '{name}' with no underlying tables")
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

    def columns(self):
        return self.etype._keys


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
    def __new__(cls, view, parent=None):
        return super().__new__(cls)

    def __init__(self, view, parent=None):
        self.view = view
        self.parent = parent

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

    @classmethod
    def size(cls):
        """ Get total size of structure, in bits

        If the structure size is variable, get the maximum possible size
        """
        return sum(field.size.eval(cls) * field.unit
                   for field in cls.fields)

    @classmethod
    def attrs(cls):
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
        elif spec == 'byname':
            return ''.join(f'{field.name}: {self[field.name]}\n'
                           for field in self.fields)
        else:
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
        name = splitext(basename(path))[0]
        rows = util.readtsv(path)
        return cls.define_from_rows(name, rows, extra_fieldtypes)

    @classmethod
    def define_from_rows(cls, name, rows, extra_fieldtypes=None):
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
        if not len(s):
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
class TableSpec:
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
        kwargs = Dict(((k, v) for k, v in row.items() if v))
        kwargs.offset = HexInt(kwargs.offset)
        kwargs.count = int(kwargs.count, 0)
        kwargs.stride = int(kwargs.stride, 0) if kwargs.stride else None
        kwargs.size = int(kwargs.size.strip(), 0) if kwargs.size else None
        return cls(**kwargs)


class Table(Sequence, RomObject):
    """ A ROM data table

    For tables without an index, 'offset' is relative to the start of the ROM,
    and indicates the location of the zeroth item in the table. The offset of
    the Nth item will be `offset + (N * stride).

    For tables with an index, 'offset' is added to the index values to convert
    them to ROM offsets. Hence, the offset of the Nth item is `offset +
    index[N]`. The stride is informational only.

    FIXME: it occurs to me that the offset calculation could be unified as
    `offset(table[N]) = table.offset + index[N] + N * table.stride`, where
    stride is 0 for indexed tables and index[N] is 0 for non-indexed tables.
    """

    def __init__(self, parent, view, spec, index=None):
        """ Create a Table

        parent: The parent object (usually a Rom)
        view:   The reference view (usually Rom.data)
        spec:   The table spec
        index:  a list of offsets within the view
        """
        self.parent = parent
        self.view = view
        self.spec = spec
        self._index = index or Index(0, spec.count, spec.stride or spec.size)
        for field in dc.fields(spec):
            if not hasattr(self, field.name):
                setattr(self, field.name, getattr(spec, field.name))

    @property
    def _struct(self):
        return self.root.map.structs.get(self.spec.type, None)

    @property
    def _field(self):
        return self.root.map.handlers[self.type](
                id=self.fid, name=self.iname, type=self.type,
                offset=FieldExpr('0'), size=FieldExpr(str(self.size)),
                display=self.display
                )

    @property
    def _isz_bits(self):
        """ Get the size of items in the table."""
        if self.spec.size:
            return self.spec.size * self.spec.units
        elif self._struct:
            return self._struct.size()
        elif isinstance(self._index, Index):
            return self._index.stride * self.spec.units
        else:
            ident = self.name or self.fid or 'unknown'
            msg = f"Couldn't figure out size of items in {ident} table"
            raise ValueError(msg)

    def _subview(self, i):
        start = (self.offset + self._index[i]) * self.units
        end = start + self._isz_bits
        return self.view[start:end]

    def __str__(self):
        content = ', '.join(repr(item) for item in self)
        return f'Table({content})\n'

    def __repr__(self):
        tp = self.spec.type
        ct = len(self)
        offset = util.HexInt(self._index.offset)
        return f'<Table({tp}*{ct}@{offset})>'

    def __len__(self):
        return len(self._index)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        elif i >= len(self):
            raise IndexError(f"Table index out of range ({i} >= {len(self)})")
        elif self._struct:
            return self._struct(self._subview(i), self)
        else:
            item = RomObject(self._subview(i), self)
            return self._field.__get__(item)

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            indices = list(range(i.start, i.stop, i.step))
            if len(indices) != len(v):
                msg = "mismatched slice length; {len(indices)} != {len(v)}"
                raise ValueError(msg)
            for i, v in zip(range(i.start, i.stop, i.step), v):
                self[i] = v
        elif self._struct:
            self[i].copy(v)
        else:
            item = RomObject(self._subview(i), self)
            self._field.__set__(item, v)

    def lookup(self, name):
        try:
            return next(item for item in self if item.name == name)
        except AttributeError:
            raise AttributeError(f"Tried to look up {self.spec.type} by name, "
                                  "but they are nameless")
        except StopIteration:
            raise LookupError(f"No object with name: {name}")

    @property
    def has_index(self):
        return isinstance(self._index, Table)

    def asdict(self):
        return {'id': self.id,
                'fid': self.fid,
                'name': self.name or '',
                'iname': self.iname or '',
                'type': self.spec.type,
                'units': self.units,
                'offset': self.offset,
                'count': len(self),
                'stride': self.size or '',
                'size': self.size or '',
                'index': self._index.id if self.has_index else '',
                'display': self.spec.display,
                'comment': self.comment}


class Index(Sequence):
    def __init__(self, offset, count, stride):
        self.offset = offset
        self.count = count
        self.stride = stride

    def __len__(self):
        return self.count

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[i] for i in range(len(self))[i]]
        elif i >= self.count:
            raise IndexError("Index doesn't extend that far")
        else:
            return util.HexInt(self.offset + i * self.stride)

    def __repr__(self):
        return f"Index({self.offset}, {self.count}, {self.stride})"

    def __eq__(self, other):
        if len(self) != len(other):
            return False
        else:
            return all(a == b for a, b in zip(self, other))


class CalculatedIndex(Sequence):
    """ A calculated pseudo-index """
    class EvalContext(Mapping):
        """ A dict-like context for asteval that does lazy lookups """
        def __init__(self, tables, i):
            self.tables = tables
            self.i = i

        def __len__(self):
            return len(self.tables) + 1

        def __iter__(self):
            yield 'i'
            yield from self.tables

        def __getitem__(self, key):
            return (self.i if key == 'i'
                    else self.tables[key])

    def __init__(self, count, expr, tables):
        self.count = count
        self.expr = expr
        self.tables = tables
        self.interpreter = Interpreter({}, minimal=True)

    def __len__(self):
        return self.count

    def __str__(self):
        return self.expr

    def __repr__(self):
        return f"{type(self)}({self.expr:r}, {self.tables})"

    def __getitem__(self, i):
        if i >= len(self):
            raise IndexError(f"i >= {len(self)}")

        if isinstance(i, slice):
            return SequenceView(self, i)
        # skip the expensive bits if we can
        if self.expr in self.tables:
            return self.tables[self.expr]
        self.interpreter.symtable = self.EvalContext(self.tables, i)
        result = self.interpreter.eval(self.expr)
        errs = self.interpreter.error or []
        for err in self.interpreter.error or []:
            msg = f"error evaluating crossref: '{self.expr}': {err.msg}"
            log.error(msg)
        if errs:
            raise RomtoolError(msg)
        return result
