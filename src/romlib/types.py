import logging
import abc
from collections import Counter
from types import SimpleNamespace
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
    def __init__(self, type, offset, size, mod=None, display=None, **kwargs):
        if isinstance(offset, str):
            offset = Offset.from_spec(offset)
        if isinstance(size, str):
            size = Size.from_spec(size)
        if isinstance(mod, str) and 'int' in _type:
            mod = int(mod, 0)
        if 'str' in type and not display:
            display = 'ascii'

        self.offset = offset
        self.size = size
        self.typename = type
        self.mod = mod
        self.display = display

    # These are implemented as get/set methods so that they can be overridden
    # in plugins. Necessary for things like unions, e.g. the effectivity spell
    # byte in ff1.

    @property
    def is_struct(self):
        return self.typename in Structure.registry

    @property
    def is_int(self):
        return 'int' in self.typename

    @property
    def is_str(self):
        return self.typename == 'str'

    @property
    def type(self):
        if self.typename in Structure.registry:
            return Structure.registry(self.typename)
        elif 'int' in self.typename and self.display == 'hex':
            return util.HexInt
        elif 'int' in self.typename:
            return int
        else:
            msg = f"Don't know what to do with a {self.typename}"
            raise NotImplementedError(msg)

    def __get__(self, obj, owner=None):
        if obj is None:
            return self

        offset = self.offset.resolve(obj)
        sz_bits = self.size.resolve(obj)
        obj.stream.pos = offset

        if self.is_struct:
            return self.type(obj.stream, offset)
        elif self.is_int:
            bits = obj.stream.readbits(sz_bits)
            read = converters.reader(self.typename)
            return self.type(read(bits))
        elif self.is_str:
            bits = obj.stream.readbits(sz_bits)
            return bits.bytes.decode(self.display)
        else:
            msg = f"Don't know what to do with a {self.typename}"
            raise NotImplementedError(msg)

    def __set__(self, obj, value):
        offset = self.offset.resolve(obj)
        sz_bits = self.size.resolve(obj)
        obj.stream.pos = offset

        if self.is_struct:
            raise NotImplementedError("Can't set entire structure at once yet")
        elif self.is_int:
            write = converters.writer(self.typename)
            bits = write(value, length=sz_bits)
            obj.stream.writebits(bits)
        elif self.is_str:
            orig_str = self.__get__(obj)
            if orig_str == value:
                return
            _bytes = value.encode(self.display)
            obj.stream.writebytes(_bytes)
        else:
            msg = f"Don't know what to do with a {self.typename}"
            raise NotImplementedError(msg)

    @classmethod
    def from_spec(cls, spec, **defaults):
        spec = {k: v if v else defaults[k]
                for k, v in spec.items() if v}
        return cls(
                _type=spec['type'],
                offset=Offset.from_spec(spec['offset'])
                size=Size.from_spec(spec['size'])
                mod=int(spec['mod'], 0)
                display=spec['display']
                )


class Structure(Mapping):
    registry = {}
    labels = {}

    def __init__(self, stream, offset):
        self.stream = stream
        self.offset = offset

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


class BitField(Structure):
    def __str__(self):
        return ''.join(str(v) for v in self.values())

    def parse(self, s):
        if len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        for k, letter in zip(self, s):
            yield letter.isupper()


class Table(Sequence):
    def __init__(self, stream, factory, index):
        """ Create a Table

        stream: The underlying bitstream
        index: a list of offsets within the stream
        factory: a callable that takes a bitstream and offset, and returns that
                 object.

        In most cases the factory will be a Structure class or Primitive
        instance.
        """

        self.stream = stream
        self.index = index
        self.factory = factory

    def __getitem__(self, i):
        offset = self.index[i]
        return self.factory(self.stream, offset)

    def __setitem__(self, i, v):
        self.factory.write(self.stream, self.index[i], v)

    def __len__(self):
        return len(self.index)


class Array(Table):
    def __init__(self, stream, factory, offset, count, stride, scale=8):
        index = [(offset + stride * i) * scale
                 for i in range(count)]
        super().__init__(stream, factory, index)
