import logging
import abc
from collections import Counter, ChainMap
from types import SimpleNamespace
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fixedint import FixedInt
from bitarray import bitarray
from bitarray.util import int2ba, ba2int

import bitstring
import yaml
import asteval

from . import util

""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""

log = logging.getLogger(__name__)


class Origin(enum.Enum):
    rom = 'rom'
    parent = 'parent'

    def __contains__(self, item):
        return item in self.__members__ or super().__contains__(item)


class Unit(enum.IntEnum):
    bits = 1
    bytes = 8
    kb = 1024

    def __contains__(self, item):
        return item in self.__members__ or super().__contains__(item)


class Offset:
    def __init__(self, expr, unit=Unit.bytes, origin=Origin.relative):
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
            elif expr is None:
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
            return self.count * self.scale


class Field:
    def __init__(self, cls, offset, mod=None):
        if isinstance(mod, str) and issubclass(cls, int):
            mod = int(mod, 0)
        self.cls = cls
        self.size = size
        self.mod = mod
        self.offset = offset

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
        offset = Offset.define(spec['offset'])
        size = Size.define(spec['size'])
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
                    msg =  f"duplicated field id or label: '{name}.{ident}'"
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


# NOTE FOR MORNING: This won't work with fixedint, because I can't subclass
# FixedInt. But I think I can do something similar myself. Make a fixedint
# class of my own with a define() classmethod that returns a subclass with a
# specific size, byte-endianness, etc. Nothing signed.
#
# When to enforce size? In __new__? Take a look at how fixedint does it.
#
# alternative, I can't subclass FixedInt, but I *can* subclass the
# classes it returns...do so, and add the appropriate methods via multiple
# inheritance. Will that work?

def uint_cls(tpname, sz_bits, fmt=None):
    registry = {'uint': uint_mixin,
                'uintle': uintle_mixin,
                'uintbe': uintbe_mixin}
    if tpname not in registry:
        return None

    bases = [FixedInt(width=sz_bits, signed=False, mutable=False)]
    if fmt == 'hex':
        bases.append(fixedint.util.HexFormattingMixin)  # Love that this is builtin
    bases.append(registry[tpname])
    bases.reverse()
    clsname = f'{tpname}{sz_bits}'

    newcls = type(clsname, bases, {})
    return newcls


class uint_mixin:
    @classmethod
    def from_bits(cls, ba):
        return cls(ba2int(ba), width=len(ba), signed=False, mutable=False)

    @classmethod
    def from_stream(cls, stream):
        return cls.from_bits(stream.readbits(cls.width))

    def to_bits(self):
        return int2ba(self, length=self.width)

    def to_stream(self, stream):
        stream.writebits(self.to_bits())

    # Convenience properties
    @property
    def bits(self):
        return self.to_bits()

    @property
    def bytes(self):
        return self.to_bytes()


class uintle_mixin(uint):
    def to_bytes(self, byteorder='little'):
        return super().to_bytes(byteorder)

    def to_bits(self):
        _bytes = self.to_bytes()
        ba = bitarray()
        ba.frombytes(_bytes)
        return ba

    @classmethod
    def from_bits(cls, ba):
        return cls.from_bytes(ba.tobytes(), byteorder='little', signed=False)


class uintbe_mixin(uint):
    def to_bytes(self, byteorder='big'):
        return super().to_bytes(byteorder)

    def to_bits(self):
        _bytes = self.to_bytes()
        ba = bitarray()
        ba.frombytes(_bytes)
        return ba

    @classmethod
    def from_bits(cls, ba):
        return cls.from_bytes(ba.tobytes(), byteorder='big', signed=False)


class Array(Table):
    def __init__(self, stream, factory, offset, count, stride, scale=8):
        index = [(offset + stride * i) * scale
                 for i in range(count)]
        super().__init__(stream, factory, index)
