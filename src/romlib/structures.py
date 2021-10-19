""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import logging
from collections.abc import Mapping, Sequence
from itertools import chain, combinations
from os.path import basename, splitext
from io import BytesIO

import yaml
from anytree import NodeMixin

from .types import Field
from . import util
from .io import Unit


log = logging.getLogger(__name__)

# I think I need one more layer of mappings here; an "entity" class that
# corresponds to array sets in the array spec, and forwards lookups to the
# underlying structures. The current design makes it hard to e.g. set the hp on
# an entity with name N if the name and hp are in different, parallel tables.

class Entity:
    structs = []  # so setattr has something to iterate over

    def __init__(self, structs):
        super().__setattr__('structs', list(structs))

    def __getitem__(self, key):
        for struct in self.structs:
            if key in struct:
                return struct[key]
        raise KeyError(f"no field with name '{key}'")

    def __setitem__(self, key, value):
        for struct in self.structs:
            if key in struct:
                struct[key] = value
        raise KeyError(f"no field with name '{key}'")

    def __getattr__(self, attr):
        for struct in self.structs:
            if hasattr(struct, attr):
                return struct.attr
        raise AttributeError(f"no field with id: '{attr}'")

    def __setattr__(self, attr, value):
        for struct in self.structs:
            if hasattr(struct, attr):
                setattr(struct, attr, value)
                return
        raise AttributeError(f"no field with id: '{attr}'")

    # TODO: add equivalent of Structure.__iter__, keys(), etc...so we can
    # get output headers in the right order more easily.


class Structure(Mapping, NodeMixin):
    """ A structure in the ROM."""

    registry = {}
    labels = {}

    def __init__(self, view, parent=None):
        self.view = view
        self.parent = parent

    def _subview(self, field):
        # This ugliness is supposed to get us a bitarrayview of a single field
        # It's surprisingly difficult to handle int, str, and None values
        # concisely.
        context = (self.view if field.origin is None
                   else self.view.root if field.origin == 'root'
                   else self.view.root.find(field.origin))

        mapper = {str: lambda v: getattr(self, v) * field.unit,
                  int: lambda v: v * field.unit,
                  type(None): lambda v: v}

        offset = mapper[type(field.offset)](field.offset)
        size = mapper[type(field.size)](field.size)
        end = (size if not offset
               else offset + size if size
               else None)
        return context[offset:end]

    def _get(self, field):
        """ Plumbing behind getitem/getattr """
        subview = self._subview(field)
        if field.type in self.registry:
            return Structure.registry[field.type](subview, self)
        else:
            return field.read(subview)

    def _set(self, field, value):
        if field.type in self.registry:
            value.copy(self._get_struct(field))
        else:
            subview = self._subview(field)
            field.write(subview, value)

    def __getitem__(self, key):
        return self._get(self._fbnm(key))

    def __setitem__(self, key, value):
        self._set(self._fbnm(key), value)

    def __getattr__(self, key):
        return self._get(self._fbid(key))

    def __setattr__(self, key, value):
        # TODO: don't allow setting new attributes after definition is done.
        try:
            self._set(self._fbid(key), value)
        except AttributeError:
            super().__setattr__(key, value)

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
        return sum(field.size * field.unit for field in cls.fields)


    def __iter__(self):
        return (f.name for f in self.fields)

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
        return yaml.dump(dict(self))

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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        name = cls.__name__
        if name in cls.registry:
            log.warning("duplicate definition of '%s'", name)
        cls.registry[name] = cls

    @classmethod
    def define(cls, name, fields):
        """ Define a type of structure from a list of Fields

        The newly-defined type will be registered and returned.
        """
        fields = list(fields)
        fids = [f.id for f in fields]
        names = [f.name for f in fields]
        for identifier in chain(fids, names):
            if hasattr(cls, identifier):
                msg = f"{name}.{identifier} shadows a built-in attribute"
                raise ValueError(msg)

        for a, b in combinations(fields, 2):
            dupes = set(a.identifiers) & set(b.identifiers)
            if dupes:
                msg = f"Duplicate identifier(s) in {name} spec: {dupes}"
                raise ValueError(msg)

        bases = (cls,)
        attrs = {'fields': fields}
        return type(name, bases, attrs)

    @classmethod
    def define_from_tsv(cls, path):
        name = splitext(basename(path))[0]
        fields = [Field.from_tsv_row(row)
                  for row in util.readtsv(path)]
        return cls.define(name, fields)

    def copy(self, other):
        """ Copy all attributes from one struct to another"""
        for k, v in self.items():
            if isinstance(v, Mapping):
                v.copy(other[k])
            else:
                other[k] = v

    def load(self, tsv_row):
        for field in self.fields:
            key = field.name
            if isinstance(self[key], BitField):
                old = str(self[key])
                self[key].parse(tsv_row[key])
                new = str(self[key])
                if old != new:
                    log.debug("changed: %s:%s (%s -> %s)",
                              type(self).__name__, key, old, new)
            else:
                value = field.parse(tsv_row[field.name])
                old = str(self[key])
                new = str(value)
                if old != new:
                    log.debug("changed: %s:%s (%s -> %s)",
                              type(self).__name__, key, old, new)
                self[key] = value


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


class Table(Sequence, NodeMixin):

    # Can't do a registry; what if you have more than one rom open? No, the rom
    # object has to maintain tables and their names, connect indexes, etc.

    def __init__(self, view, typename, index,
                 offset=0, size=None, units=Unit.bytes, display=None,
                 parent=None):
        """ Create a Table

        view:   The underlying bitarray view
        index:  a list of offsets within the view
        cls:    The type of object contained in this table.
        """

        self.view = view
        self.parent = parent
        self.index = index
        self.units = units
        self.typename = typename
        self.offset = offset
        self.size = size
        self.display = display

    @property
    def _struct(self):
        return Structure.registry.get(self.typename, None)

    @property
    def _isz_bits(self):
        """ Get the size of items in the table."""
        if self.size:
            return self.size * self.units
        elif self._struct:
            return self._struct.size()
        elif isinstance(self.index, Index):
            return self.index.stride * self.units
        else:
            raise ValueError("Couldn't figure out item size")

    def _subview(self, i):
        start = (self.offset + self.index[i]) * self.units
        end = start + self._isz_bits
        return self.view[start:end]

    def __repr__(self):
        content = ', '.join(repr(item) for item in self)
        return f'Table({content})\n'

    def __getitem__(self, i):
        if isinstance(i, slice):
            return Table(self.view, self.typename, self.index[i])
        elif i >= len(self):
            raise IndexError("Table index out of range")
        elif self._struct:
            return self._struct(self._subview(i), self)
        elif self.typename == 'str':
            return self._subview(i).bytes.decode(self.display)
        elif self.typename == 'strz':
            return self._subview(i).bytes.decode(self.display + '-clean')
        elif self.display in ('hex', 'pointer'):
            return util.HexInt(getattr(self._subview(i), self.typename))
        else:
            return getattr(self._subview(i), self.typename)

    def lookup(self, name):
        try:
            return next(item for item in self if item.name == name)
        except AttributeError:
            raise LookupError(f"Tried to look up {self.typename} by name, "
                               "but they are nameless")
        except StopIteration:
            raise ValueError(f"No object with name: {name}")

    def locate(self, name):
        """ Get the index of a structure with the given name """
        try:
            return next(i for i, item in enumerate(self)
                        if item == name or item.name == name)
        except AttributeError:
            raise LookupError(f"Tried to look up {self.typename} by name, "
                               "but they are nameless")
        except StopIteration:
            raise ValueError(f"No object with name: {name}")

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

        if self._struct:
            self[i].copy(v)
        elif  self.typename in ('str', 'strz'):
            encoding = ('ascii' if not self.display
                        else self.display + '-clean' if self.typename == 'strz'
                        else self.display)
            bv = self._subview(i)
            # Avoid spurious patch changes when there's more than one way
            # to encode the same string
            old = bv.bytes.decode(encoding)
            if v == old:
                return
            # This smells. Duplicates the process in Field._set_str.
            content = BytesIO(bv.bytes)
            content.write(v.encode(encoding))
            content.seek(0)
            bv.bytes = content.read()
        else:
            setattr(self._subview(i), self.typename, v)

    def __len__(self):
        return len(self.index)

    @classmethod
    def from_tsv_row(cls, row, parent, view=None):
        if not view:
            view = parent.view

        # Filter out empty strings
        row = {k: v for k, v in row.items() if v}
        typename = row['type']
        offset = int(row.get('offset', '0'), 0)
        units = Unit[row.get('unit', 'bytes')]
        size = int(row['size'], 0) if 'size' in row else None
        display = row.get('display', None)
        if 'index' in row:
            index = getattr(parent, row['index'])
        else:
            count = int(row['count'], 0)
            stride = int(row.get('stride', '0'), 0)
            index = Index(0, count, stride)
        return Table(view, typename, index, offset, size, units, display, parent)


class Index(Sequence):
    def __init__(self, offset, count, stride):
        self.offset = offset
        self.count = count
        self.stride = stride

    def __len__(self):
        return self.count

    def __getitem__(self, i):
        if isinstance(i, slice):
            return (self[i] for i in range(i.start, i.stop, i.step))
        elif i >= self.count:
            raise IndexError("Index doesn't extend that far")
        else:
            return self.offset + i * self.stride

    def __repr__(self):
        return f"Index({self.offset}, {self.count}, {self.stride})"

    def __eq__(self, other):
        if len(self) != len(other):
            return False
        else:
            return all(a == b for a, b in zip(self, other))
