import logging
import abc
from collections import Counter
from types import SimpleNamespace
from collections.abc import Mapping, Sequence

import bitstring
import yaml

from . import util, primitives

# TODO: hungarian notation; bit_offset, byte_offset, bit_size, etc? Or just always use an
# Offset object with bits/bytes as attributes? I keep having to remember when to
# multiply by eight.


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
        except KeyError as err:
            raise ValueError(f"Invalid size spec: {spec}")

        return cls(scale, count, sibling)

class Offset:
    _unit_scale = {'bits': 1,
                   'bytes': 8}
    _relativity = {'rom': False,
                   'parent': True}

    """ Offset of a field or structure """
    def __init__(self, origin='parent', scale=8, count=0, sibling=None):
        self.origin = origin
        self.scale = scale
        self.count = count
        self.sibling = sibling
        self.relative = self._relativity[origin]

    def resolve(self, obj):
        start = obj.offset if self.relative else 0
        offset = obj[sibling] if self.sibling else self.count
        return start + offset

    @classmethod
    def from_spec(cls, spec):
        """ Create an offset from a string spec

        The string spec format is origin:unit:count. Origin and unit are
        optional. Origin can be 'rom' or 'parent', defaulting to parent. Unit
        can be 'bits' or 'bytes, defaulting to bytes. 'count' can be a fixed
        number or the name of a field in the parent structure.
        """
        parts = spec.split(":")
        ct_raw = parts.pop()
        try:
            count = int(ct_raw, 0)
            sibling = None
        except (ValueError, TypeError):
            count = None
            sibling = ct_raw

        origin = 'parent'
        scale = 8
        for part in parts:
            if part in _unit_scale:
                scale = _unit_scale[part]
            elif part in _relativity:
                origin = part
            else:
                raise ValueError("Invalid offset spec: " + spec)
        return cls(origin, scale, count, sibling)


class Field:
    def __init__(self, _type, offset, size, mod=None, display=None,
            **kwargs):
        if isinstance(offset, str):
            offset = Offset.from_spec(offset)
        if isinstance(size, str):
            size = Size.from_spec(size)

        self.offset = offset
        self.size = size
        self.type = _type
        self.display = display
        self.factory = primitives.getcls(_type)
        # code smell: special behavior for ints/strings
        if issubclass(self.factory, int):
            self.bstype = _type
            self.mod = util.intify(mod, None)
        elif _type == 'str':
            self.bstype = 'bits'
            self.mod = mod
            self.display = display or 'ascii'
        else:
            self.bstype = 'bin'
            self.mod = mod

    def __get__(self, obj, owner=None):
        if obj is None:
            # We might actually want to do this sometimes, e.g. to print
            # information about a field at the type level
            return self
        stream = obj.stream
        offset = self.offset.resolve(obj)
        size = self.size.resolve(obj)
        spec = f'{self.bstype}:{size}'

        stream.pos = offset
        value = stream.read(spec)
        if self.factory is str:
            value = value.bytes.decode(self.display)
        else:
            value = self.factory(value, size, self.display)

        if self.mod:
            value = value.mod(self.mod)
        return value

    def __set__(self, obj, value):
        stream = obj.stream
        offset = self.offset.resolve(obj)
        size = self.size.resolve(obj)
        if self.factory is str:
            value = bitstring.Bits(value.encode(self.display))
        else:
            value = self.factory(value, size, self.display)
        if self.mod:
            value = value.unmod(self.mod)

        stream.pos = offset
        stream.overwrite(f'{self.bstype}:{size}={value}')


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

    @classmethod
    def define(cls, name, field_dicts, force=False):
        """ Define a type of structure from a list of stringdicts

        The newly-defined type will be registered and also returned.
        """
        if name in cls.registry and not force:
            raise ValueError(f"duplicate definition of '{name}'")

        fields = {'labels': {}}
        labels = fields['labels']
        for dct in field_dicts:
            f = SimpleNamespace(**dct)  # For dot lookups
            for ident in f.id, f.label:
                if hasattr(cls, ident):
                    msg = f"field id or label '{name}.{ident}' shadows a built-in attribute"
                    raise ValueError(msg)
                if ident in fields or ident in labels:
                    msg =  "duplicated field id or label: '{name}.{ident}'"
                    raise ValueError(msg)
            fields[f.id] = (Field(f.type, f.offset, f.size, f.mod))
            labels[f.label] = f.id
        struct_subclass = type(name, (cls,), fields)
        cls.registry[name] = struct_subclass
        return struct_subclass


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

    @classmethod
    def build_index(offset, count, stride, scale=8):
        return [(offset + stride * i) * scale
                for i in range(count)]

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
