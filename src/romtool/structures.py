""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import dataclasses as dc
import logging
from collections.abc import Mapping, Sequence, MutableMapping
from itertools import chain, combinations, groupby
from functools import partial, lru_cache
from contextlib import contextmanager
from os.path import basename, splitext
from io import BytesIO
from abc import ABC

import yaml
from addict import Dict
from anytree import NodeMixin

from .field import Field, StructField, FieldExpr
from . import util
from .util import RomObject, SequenceView, CheckedDict, HexInt
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

    def locate(self, name):
        """ Get the index of the entity with the given name """
        try:
            return next(i for i, e in enumerate(self) if e.name == name)
        except AttributeError:
            raise LookupError(f"Tried to look up {self.name} by name, "
                               "but they are nameless")
        except StopIteration:
            raise ValueError(f"No object with name: {name}")

    @classmethod
    @contextmanager
    def cache_locate(cls):
        """ Temporarily cache locate calls

        This is supposed to help with the abysmal slowness of resolving
        cross-references in tsv input files. I'm pretty sure this is a terrible
        idea and will bite me at some point.

        The cache will return stale results if the name of an entity changes
        between cross-references. This *shouldn't* happen during changeset
        loading, but could easily happen during other use, hence it not being
        the default behavior.
        """
        orig_locate = cls.locate
        cls.locate = lru_cache(None)(cls.locate)
        try:
            yield cls
        finally:
            cls.locate = orig_locate


class Structure(Mapping, NodeMixin, RomObject):
    """ A structure in the ROM."""

    @lru_cache(None)
    def __new__(cls, view, parent=None):
        return super().__new__(cls)

    def __init__(self, view, parent=None):
        self.view = view
        self.parent = parent

    def __getitem__(self, key):
        return self._fbnm(key).read(self)

    def __setitem__(self, key, value):
        self._fbnm(key).write(self, value)

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
    def fids(self):
        return [f.id for f in self.fields]

    @classmethod
    def _fbid(cls, fid):
        """ Get field by fid """
        # Consider functools.lru_cache if this is slow.
        try:
            return next(f for f in cls.fields if f.id == fid)
        except StopIteration as ex:
            raise AttributeError(f"No such field: {cls.__name__}.{fid}") from ex

    @classmethod
    def _fbnm(cls, fnm):
        """ Get field by name """
        try:
            return next(f for f in cls.fields if f.name == fnm)
        except StopIteration as ex:
            raise KeyError(f"No such field: {cls.__name__}[{fnm}])") from ex

    @classmethod
    def size(cls):
        """ Get total size of structure, in bits

        If the structure size is variable, get the maximum possible size
        """
        return sum(field.size.eval(cls) * field.unit
                   for field in cls.fields)

    def __iter__(self):
        # Keys are technically unordered, but in many places it's very
        # convenient for the name to come 'first'.
        return (f.name for f in sorted(self.fields))

    def __len__(self):
        return len(self.fields)

    def _debug(self):
        return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                       for field in self.fields)

    def __format__(self, spec):
        outfmt, identifier = spec.split(":")
        if outfmt != 'y':
            raise ValueError("bad format string: {spec}")
        if identifier == 'i':
            return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                           for field in self.fields)
        elif identifier == 'n':
            return ''.join(f'{field.name}: {self[field.name]}\n'
                           for field in self.fields)
        else:
            raise ValueError("bad format string: {spec}")

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
        """ Define a type of structure from a list of Fields

        The newly-defined type will be registered and returned.
        """
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
        fields = [Field.from_tsv_row(row, extra_fieldtypes)
                  for row in rows]
        return cls.define(name, fields)

    def copy(self, other):
        """ Copy all attributes from one struct to another"""
        for k, v in self.items():
            if isinstance(v, Mapping):
                v.copy(other[k])
            else:
                other[k] = v

    def load(self, tsv_row):
        def stdparse(field):
            """ helper that serves as both "normal" parser and fallback"""
            key = field.name
            value = field.parse(tsv_row[field.name])
            old = str(self[key])
            new = str(value)
            if old != new:
                log.debug("changed: %s:%s (%s -> %s)",
                          type(self).__name__, key, old, new)
            self[key] = value


        for field in self.fields:
            key = field.name
            if isinstance(self[key], BitField):
                old = str(self[key])
                self[key].parse(tsv_row[key])
                new = str(self[key])
                if old != new:
                    log.debug("changed: %s:%s (%s -> %s)",
                              type(self).__name__, key, old, new)
            elif field.ref:
                etbl = self.root.entities[field.ref]
                try:
                    self[key] = etbl.locate(tsv_row[key])
                except ValueError:
                    try:
                        stdparse(field)
                    except ValueError:
                        msg = ("{stnm}.{fid} must be either an index or a "
                               "valid name from '{ref}'; '{val}' is neither")
                        msg = msg.format(
                                stnm=type(self).__name__,
                                fid=field.id,
                                ref=field.ref,
                                val=tsv_row[key]
                                )
                        raise ValueError(msg)
            else:
                stdparse(field)


class BitField(Structure):
    # FIXME: this is the next thing that needs doing, I think.
    def __str__(self):
        return ''.join(field.display.upper() if self[field.name]
                       else field.display.lower()
                       for field in self.fields)

    def __repr__(self):
        tpnm = type(self).__name__
        offset = str(util.HexInt(self.view.abs_start,
                                 len(self.view.root).bit_length()))
        return f"<{tpnm}@{offset} ({str(self)})>"

    def parse(self, s):
        if len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        for k, letter in zip(self, s):
            self[k] = letter.isupper()


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


class Table(Sequence, NodeMixin, RomObject):
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
        self.index = index or Index(0, spec.count, spec.stride or spec.size)
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
        elif isinstance(self.index, Index):
            return self.index.stride * self.spec.units
        else:
            ident = self.name or self.fid or 'unknown'
            msg = f"Couldn't figure out size of items in {ident} table"
            raise ValueError(msg)

    def _subview(self, i):
        start = (self.offset + self.index[i]) * self.units
        end = start + self._isz_bits
        return self.view[start:end]

    def __str__(self):
        content = ', '.join(repr(item) for item in self)
        return f'Table({content})\n'

    def __repr__(self):
        tp = self.spec.type
        ct = len(self)
        offset = util.HexInt(self.index.offset)
        return f'<Table({tp}*{ct}@{offset})>'

    def __len__(self):
        return len(self.index)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        elif i >= len(self):
            raise IndexError(f"Table index out of range ({i} >= {len(self)})")
        elif self._struct:
            return self._struct(self._subview(i), self)
        else:
            return self._field.read(self._subview(i))

    def __setitem__(self, i, v):
        if str(v) != str(self[i]):
            log.debug("difference detected: %r != %r", v, self[i])
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
            self._field.write(self._subview(i), v)

    def lookup(self, name):
        try:
            return next(item for item in self if item.name == name)
        except AttributeError:
            raise AttributeError(f"Tried to look up {self.spec.type} by name, "
                                  "but they are nameless")
        except StopIteration:
            raise LookupError(f"No object with name: {name}")

    def locate(self, name):
        """ Get the index of a structure with the given name """
        try:
            return next(i for i, item in enumerate(self)
                        if item == name or item.name == name)
        except AttributeError:
            raise LookupError(f"Tried to look up {self.spec.type} by name, "
                               "but they are nameless")
        except StopIteration:
            raise ValueError(f"No {self.id} named {name}")

    @property
    def has_index(self):
        return isinstance(self.index, Table)

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
                'index': self.index.id if self.has_index else '',
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
