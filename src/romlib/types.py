import logging
import abc
from collections import Counter

import bitstring

from romlib import util


log = logging.getLogger(__name__)

class OffsetSpec(object):
    """ Specification of an offset

    This is more complicated than it seems because we want offsets to be
    able to be relative (to the parent) or absolute (in the rom). We
    also want them to be definable as a fixed number (in either case) or
    by reference to another property of the parent structure.

    The spec is: RELATIVE_TO:OFFSET_FROM_RELATIVE_POINT.

    abs:0x4000        : absolute offset 0x4000
    abs:name          : absolute offset defined by named sibling field
    rel:33            : byte 33 within parent structure
    rel:sib           : offset within parent defined by other parent field

    "rel" is the default, but can be given if desired.
    """

    def __init__(self, spec):
        self.spec = spec

        if ':' in spec:
            origin, sep, offset_raw = spec.partition(":")
        else:
            origin = 'rel'
            offset_raw = spec

        if origin not in ('rel', 'abs'):
            raise ValueError("Invalid offset spec: " + spec)

        try:
            offset = int(offset_raw, 0)
            sibling = None
        except (ValueError, TypeError):
            offset = None
            sibling = offset_raw

        self.offset = offset
        self.origin = origin
        self.sibling = sibling

    def __get__(self, instance, owner=None):
        origin = {'abs': 0, 'rel': instance.parent.offset}[self.origin]

        if self.offset is not None:
            offset = self.offset
        else:
            offset = instance.parent[self.sibling]

        return origin + offset


class SizeSpec(object):
    """ Size of a field or structure

    Size specs are UNIT:COUNT. Unit can be bits or bytes, defaulting to
    bits. Count can be a fixed number or the name of a field in the
    parent structure.
    """

    _unit_scale = {'bits': 1,
                   'bytes': 8,
                   'kb': 8*1024}

    def __init__(self, specstr):
        sz_raw, sep, unit = reversed(self.specstr)

        if not unit:
            unit = 'bits'
        if unit not in self._unit_scale:
            raise ValueError("Invalid size spec: " + spec)

        try:
            count = int(sz_raw, 0)
            sibling = None
        except (ValueError, TypeError):
            count = None
            sibling = sz_raw

        self.scale = self._unit_scale[unit]
        self.count = count
        self.sibling = sibling

    def __get__(self, instance, owner=None):
        """ Get the size of the object, in bits. """

        if self.sibling is None:
            return self.count * self.scale
        else:
            return instance.parent[self.sibling] * self.scale

class Offset:
    def __init__(self, relative, offset=None, sibling=None):
        self.relative = relative
        self.offset = offset
        self.sibling = sibling

    def resolve(self, obj):
        origin = obj.offset if self.relative else 0
        offset = obj[sibling] if self.sibling else self.scalar
        return origin + offset

    @classmethod
    def from_spec(cls, spec):
        origin, sep, offset_raw = reversed(spec.partition(':'))

        relative = {'abs': False, 'rel': True}[origin]
        try:
            offset = int(offset_raw, 0)
            sibling = None
        except (ValueError, TypeError):
            offset_raw = None
            sibling = sz_raw
        return cls(relative, offset, sibling)


class Field:
    registry = {}

    def __init__(self, _type='uint', offset='0', size=1, mod=None):
        self.offset = Offset.from_spec(offset)
        self.size = SizeSpec(size)
        self.type = _type
        self.mod = mod

    def __get__(self, obj, owner=None):
        if obj is None:
            # We might actually want to do this sometimes, e.g. to print
            # information about a field at the type level
            return self
        self._position(obj)
        value = obj.stream.read(f'{self.type}:{self.size}')
        return value

    def __set__(self, obj, value):
        self._position(obj)
        obj.stream.overwrite(f'{self.type}:{self.size}={value}')

    def _position(self, obj):
        """ Position parent object's stream for read/write """
        obj.stream.pos = obj.offset + self.offset.resolve(obj)

    def __init_subclass__(cls, **kwargs):
        cls.registry[kwargs['register']] = cls

    @classmethod
    def define(cls, dct):
        return cls.registry[dct['type']](**dct)


class HexInt(int):
    """ An integer that stringifies as hex """
    def __new__(cls, value, sz_bits=None):
        i = super().__new__(cls, value)
        i.sz_bits = sz_bits

    def __str__(self):
        return util.hexify(self, len_bits=self.sz_bits)


class UIntField(Field, register='uint'):
    def __init__(self, *args, mod=0, **kwargs):
        kwargs['mod'] = util.intify(mod, 0)
        super().__init__(self, *args, **kwargs)

    def __get__(self, obj, owner=None):
        value = super().__get__(self, obj, owner) + self.mod
        if self.display == 'hex':
            value = HexInt(value)
        return value

    def __set__(self, obj, value):
        value -= self.mod
        super().__set__(self, obj, value)


class PointerField(UIntField, register='ptr'):
    def __get__(self, obj, owner=None):
        value = super().__get__(self, obj, owner)
        return HexInt(value, self.size)


class StringField(Field, register='str'):
    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        self._position(obj)
        bs = obj.stream.read(self.sz_bits)
        return codecs.decode(bs.bytes, self.display or 'ascii')

    def __set__(self, obj, value):
        self._position(obj)
        obj.stream.overwrite(codecs.encode(s, self.display or 'ascii'))


class PrettyBits(bitstring.Bits):
    def __new__(cls, display, *args, **kwargs):
        bs = super().__new__(cls, *args, **kwargs)
        bs.display = display

    def __str__(self):
        return util.displaybits(self, self.display)


class BinField(Field, register='bin'):
    mod = 'msb0'

    def __get__(self, obj, owner=None):
        bs = super().__get__(self, obj, owner)
        if self.mod == 'lsb0':
            bs = util.lbin_reverse(bs)
        return PrettyBits(self.display, bs)


class Structure:
    registry = {}
    labels = {}

    def __getitem__(self, key):
        return getattr(self, self.lookup[key])

    def __setitem__(self, key, value):
        setattr(self, self.lookup[key], value)

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
            labels[f.label] = f.fid
        struct_subclass = type(name, (cls,), fields)
        cls.registry[name] = struct_subclass
        return struct_subclass


class Structure:
    registry = {}

    # fields should be a list of Field subclasses. They will be used to
    # instantiate instance data when Structure itself is instantiated.
    fields = []

    def __init__(self, stream, offset):
        # FIXME: Check behavior vs get/setattr
        super().__setattr__('stream', stream)
        super().__setattr__('offset', offset)
        super().__setattr__('data', dict())
        for fieldcls in self.fields:
            print(fieldcls)
            field = fieldcls(self)
            print(field)
            # We want to be able to look up data by either id or label
            self.data[field.fid] = field
            self.data[field.label] = field

    def __init_subclass__(cls, **kwargs):
        # Sanity check fields
        for field in cls.fields:
            if field.fid in dir(cls):
                msg = "field id {field.__name__} shadows a built-in attribute"
                raise ValueError(msg)

        names = [f.fid for f in cls.fields] + [f.label for f in cls.fields]
        for name, count in Counter(names).items():
            if count > 1:
                msg = "duplicated field id or label: '{cls.__name__}.{name}'"
                raise ValueError(msg)

        # Register the structure type
        cls.registry[cls.__name__] = cls

    @classmethod
    def define(cls, name, field_dicts, force=False):
        """ Define a type of structure from a list of stringdicts

        The newly-defined type will be registered and also returned.
        """
        if name in cls.registry and not force:
            raise ValueError(f"duplicate definition of '{name}'")

        subclass = type(name, (cls,), {})
        for dct in field_dicts:
            setattr(subclass, dct['fid'], Field.define(dct))
        cls.registry[name] = struct_subclass
        return struct_subclass

    def dump(self, use_labels=True):
        out = {}
        for field in self.fields:
            key = field.label if use_labels else field.fid
            out[key] = self[key]
        return out

    def __str__(self):
        return yaml.dump(self.items())

    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value

    def __getitem__(self, key):
        return self.data[key].read()

    def __setitem__(self, key, value):
        self.data[key].write(value)

    def __iter__(self):
        for field in self.fields:
            yield field.fid

    def __len__(self):
        return len(self.fields)
