""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import logging
import enum
from types import SimpleNamespace
from collections.abc import Mapping, Sequence

import yaml

from .primitives import uint_cls
from . import util


log = logging.getLogger(__name__)


class Origin(enum.Enum):
    rom = 'rom'
    parent = 'parent'

    def __contains__(self, item):
        return item in type(self).__members__ or super().__contains__(item)


class Unit(enum.IntEnum):
    bits = 1
    bytes = 8
    kb = 1024

    def __contains__(self, item):
        return item in type(self).__members__


class Offset:
    def __init__(self, expr, unit=Unit.bytes, origin=Origin.parent):
        expr = str(expr)  # Just in case someone passes int
        self.expr = expr
        self.origin = origin
        self.unit = unit
        try:
            self.count = int(self.expr, 0)
        except ValueError:
            # We'll have to calc it on the fly.
            self.count = None

    @property
    def is_static(self):
        return self.count is not None

    @property
    def absolute(self):
        return self.origin is Origin.rom

    @property
    def relative(self):
        return self.origin is Origin.parent

    def eval(self, context=None):
        if self.is_static:
            count = self.count
        else:
            count = util.aeval(self.expr, context)
        return count * self.unit

    @classmethod
    def define(cls, spec, **defaults):
        parts = spec.split(':')
        kwargs = defaults.copy()
        for part in parts:
            if part in Unit:
                kwargs['unit'] = Unit[part]
            elif part in Origin:
                kwargs['origin'] = Origin[part]
            elif 'expr' not in kwargs:
                kwargs['expr'] = part
            else:
                raise ValueError(f"Invalid offset spec: {spec}")
        return cls(**kwargs)


class Size:
    def __init__(self, count, unit=Unit.bytes):
        self.count = count
        self.unit = unit

    @property
    def bits(self):
        return self.count * self.unit

    @classmethod
    def define(cls, spec, **defaults):
        parts = spec.split(':')
        kwargs = defaults.copy()
        for part in parts:
            if part in Unit:
                kwargs['unit'] = Unit[part]
            elif 'expr' not in kwargs:
                kwargs['expr'] = part
            else:
                raise ValueError(f"Invalid size spec: {spec}")
        return cls(**kwargs)


class Field:
    def __init__(self, cls, offset, size=None, mod=None):
        if isinstance(mod, str) and issubclass(cls, int):
            mod = int(mod, 0)
        self.cls = cls
        self.size = size
        self.mod = mod
        self.offset = offset
        self.name = None  # Specified by set_name below

    def _resolve_offset(self, obj):
        origin = 0 if self.offset.absolute else obj.offset
        return origin + self.offset.eval(obj)

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        obj.stream.pos = self._resolve_offset(obj)
        value = self.cls.from_stream(obj.stream)
        if self.mod:
            value += self.mod
        return value

    def __set__(self, obj, value):
        if self.mod:
            value -= self.mod
        obj.stream.pos = self._resolve_offset(obj)
        value.to_stream(obj.stream)

    def __set_name__(self, owner, name):
        # Maybe useful for error messages/logging...
        self.name = '{}.{}'.format(owner.__name__, name)

    @classmethod
    def define(cls, spec, **defaults):
        spec = dict(**defaults, **spec)
        offset = Offset.define(spec['offset'])
        size = Size.define(spec['size']) if 'size' in spec else None
        mod = spec['mod']
        tpname = spec['type']

        instance_cls = (Structure.registry.get(tpname, None)
                        or uint_cls(tpname, size.bits)
                        or None)

        if instance_cls is None:
            raise ValueError(f"type '{tpname}' not found")

        return cls(instance_cls, offset, mod)


class Structure(Mapping):
    """ A structure in the ROM."""

    registry = {}
    labels = {}

    @classmethod
    def lookup(cls, tpname):
        return cls.registry.get(tpname, None)

    def __init__(self, stream, offset, parent=None):
        self.stream = stream
        self.offset = offset
        self.parent = parent

    @classmethod
    def from_stream(cls, stream):
        return cls(stream, stream.bitpos)

    def __getitem__(self, key):
        return getattr(self, self.labels.get(key, key))

    def __setitem__(self, key, value):
        setattr(self, self.labels.get(key, key), value)

    def __iter__(self):
        return iter(self.labels.values())

    def __len__(self):
        return len(self.labels)

    def __str__(self):
        return yaml.dump(dict(self))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        name = cls.__name__
        if name in cls.registry:
            raise ValueError(f"duplicate definition of '{name}'")
        cls.registry[name] = cls

    @classmethod
    def define(cls, name, field_dicts):
        """ Define a type of structure from a list of stringdicts

        The newly-defined type will be registered and returned.
        """
        attrs = {'labels': {}}
        labels = attrs['labels']

        for dct in field_dicts:
            f = SimpleNamespace(**dct)  # For dot lookups
            for ident in f.id, f.label:
                if hasattr(cls, ident):
                    msg = f"field id or label '{name}.{ident}' shadows a built-in attribute"
                    raise ValueError(msg)
                if ident in attrs or ident in labels:
                    msg = f"duplicated field id or label: '{name}.{ident}'"
                    raise ValueError(msg)
            attrs[f.id] = Field.define(dct)
            labels[f.label] = f.id
        return type(name, (cls,), attrs)

    def copy(self, other):
        """ Copy all attributes from one struct to another"""
        for k, v in self.items():
            if isinstance(v, Mapping):
                v.copy(other[k])
            else:
                other[k] = v

    def to_stream(self, stream):
        if self.offset != stream.bitpos:
            self.copy(self.from_stream(stream))


class BitField(Structure):
    def __str__(self):
        return ''.join(label.upper() if self[label] else label.lower()
                       for label in self.labels.keys())

    def parse(self, s):
        if len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        for k, letter in zip(self, s):
            self[k] = letter.isupper()


class Table(Sequence):
    def __init__(self, stream, cls, index):
        """ Create a Table

        stream: The underlying bitstream
        index:  a list of offsets within the stream
        cls:    The type of object contained in this table.
        """

        self.stream = stream
        self.index = index
        self.cls = cls

    def __getitem__(self, i):
        self.stream.bitpos = self.index[i]
        return self.cls.from_stream(self.stream)

    def __setitem__(self, i, v):
        self.stream.bitpos = self.index[i]
        v.to_stream(self.stream)

    def __len__(self):
        return len(self.index)


class Array(Table):
    def __init__(self, stream, cls, offset, count, stride, scale=8):
        index = [(offset + stride * i) * scale
                 for i in range(count)]
        super().__init__(stream, cls, index)
