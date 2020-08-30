import logging
import abc
from collections import Counter
from types import SimpleNamespace
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fixedint import FixedInt
from bitarray import bitarray
from bitarray.util import int2ba, ba2int

import bitstring
import yaml

from . import util

""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""

log = logging.getLogger(__name__)

class Size(object):
    """ Size of a field or structure """

    _unit_scale = {'bits': 1,
                   'bytes': 8,
                   'kb': 8*1024}

    def __init__(self, scale=8, count=1, sibling=None):
        if count is None and not sibling:
            raise ValueError("No specified count or sibling")
        self.count = count
        self.scale = scale
        self.sibling = sibling

    def resolve(self, instance):
        """ Get the size of the object, in bits. """

        if self.sibling is None:
            size = self.count * self.scale
        else:
            size = instance.parent[self.sibling] * self.scale
        assert isinstance(size, int)
        return size

    @classmethod
    def from_spec(cls, spec):
        """ Create a size from a string spec

        Size specs are UNIT:COUNT. Unit can be bits or bytes, defaulting to
        bits. Count can be a fixed number or the name of a field in the
        parent structure.
        """
        if ':' in spec:
            unit, sep, sz_raw = spec.partition(":")
        else:
            unit, sep, sz_raw = 'bits', '', spec

        try:
            scale = cls._unit_scale[unit]
            count = int(sz_raw, 0)
            sibling = None
        except (ValueError, TypeError):
            count = None
            sibling = sz_raw
        except KeyError:
            raise ValueError(f"Invalid size spec: {spec}")

        return cls(scale, count, sibling)


@dataclass
class Offset:
    """ Offset of a field or structure """
    _unit_scale = {'bits': 1,
                   'bytes': 8}
    _relativity = {'rom': False,
                   'parent': True}

    relative: bool = True
    scale: int = 8
    count: int = 1
    sibling: str = None

    def resolve(self, obj):
        origin = obj.offset if self.relative else 0
        offset = obj[sibling] if self.sibling else self.count
        return origin + offset

    @classmethod
    def from_spec(cls, spec):
        """ Create an offset from a string spec

        The string spec format is origin:unit:count. Origin and unit are
        optional. Origin can be 'rom' or 'parent', defaulting to parent. Unit
        can be 'bits' or 'bytes, defaulting to bytes. 'count' can be a fixed
        number or the name of a field in the parent structure.
        """
        relative = cls.relative
        scale = cls.scale
        count = cls.count
        sibling = cls.sibling

        parts = spec.split(":")
        ct_raw = parts.pop()
        try:
            count = int(ct_raw, 0)
        except (ValueError, TypeError):
            sibling = ct_raw

        for part in parts:
            if part in _unit_scale:
                scale = _unit_scale[part]
            elif part in _relativity:
                relative = _relativity[part]
            else:
                raise ValueError("Invalid offset spec: " + spec)

        return cls(relative, scale, count, sibling)


class Field:
    def __init__(self, cls, offset, mod=None):
        if isinstance(offset, str):
            offset = Offset.from_spec(offset)
        if isinstance(size, str):
            size = Size.from_spec(size)
        if isinstance(mod, str) and issubclass(cls, int):
            mod = int(mod, 0)

        self.cls = cls
        self.offset = offset
        self.size = size
        self.mod = mod

    def __get__(self, obj, owner=None):
        if obj is None:
            return self

        offset = self.offset.resolve(obj)
        obj.stream.pos = offset
        return self.cls.from_stream(obj.stream)

    def __set__(self, obj, value):
        if self.mod:
            value -= self.mod

        offset = self.offset.resolve(obj)
        obj.stream.pos = offset
        value.to_stream(obj.stream)

    @classmethod
    def from_spec(cls, spec, **defaults):
        offset = spec['offset']
        mod = spec['mod']
        size = Size.from_spec(spec['size'])
        sz_bits = size.count * size.scale
        tpname = spec['type']

        instance_cls = (Structure.registry.get(tpname, None)
                        or uint.lookup(tpname, sz_bits)
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

    def __init__(self, stream, offset):
        self.stream = stream
        self.offset = offset

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

        The newly-defined type will be registered and also returned.
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
                    msg =  "duplicated field id or label: '{name}.{ident}'"
                    raise ValueError(msg)
            attrs[f.id] = Field(f.type, f.offset, f.size, f.mod, getattr(f, 'display', None))
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
        return ''.join(str(v) for v in self.values())

    def parse(self, s):
        if len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        for k, letter in zip(self, s):
            yield letter.isupper()


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
# inheritance.

def make_uint_cls(tpname, sz_bits):
    registry = {'uint': uint_mixin,
                'uintle': uintle_mixin,
                'uintbe': uintbe_mixin}
    ficls = FixedInt(width=sz_bits, signed=False, mutable=False)
    newcls = type(tpname + str(sz_bits), (registry[tpname], ficls), {})
    return newcls


class uint_mixin:
    @classmethod
    def lookup(cls, tpname, sz_bits):
        types = {subcls.__name__: subcls
                 for subcls in cls.__subclasses__()}
        types[cls.__name__] = cls
        if tpname not in types:
            return None
        else:
            return types[tpname](width=sz_bits, signed=False, mutable=False)


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
    def to_bits(self):
        _bytes = self.to_bytes(byteorder='little')
        ba = bitarray()
        ba.frombytes(_bytes)
        return ba

    @classmethod
    def from_bits(cls, ba):
        return cls.from_bytes(ba.tobytes(), byteorder='little', signed=False)


class uintbe_mixin(uint):
    def to_bits(self):
        _bytes = self.to_bytes(byteorder='big')
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
