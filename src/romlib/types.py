import logging
import abc
from collections import Counter

import bitstring

from . import util, primitives


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
    def __init__(self, origin='parent', scale=8, count=1, sibling=None):
        self.origin = origin
        self.scale = scale
        self.count = count
        self.sibling = sibling
        self.relative = self._relativity[origin]

    def resolve(self, obj):
        start = obj.offset if self.relative else 0
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
        self.factory = primitives.get(_type)
        # code smell: special behavior for ints
        self._intish = issubclass(self.factory, int)
        self.bstype = _type if self._intish else 'bin'
        self.mod = util.intify(mod, None) if self._intish else mod

    def __get__(self, obj, owner=None):
        if obj is None:
            # We might actually want to do this sometimes, e.g. to print
            # information about a field at the type level
            return self
        stream = obj.stream
        stream.pos = self.offset.resolve(obj)
        value = stream.read(f'{self.bstype}:{self.size}')
        value = self.factory(value, self.size, self.display)
        value = value.mod(self.mod)
        return value

    def __set__(self, obj, value):
        stream = self._position(obj)
        stream.pos = self.offset.resolve(obj)
        value = self.type(value, self.size, self.display)
        value = value.unmod(self.mod)
        stream.overwrite(f'{self.bstype}:{self.size}={value}')

    @classmethod
    def from_spec(cls, dct):
        dct = dct.copy()
        dct['_type'] = dct.pop('type')
        dct['offset'] = Offset.from_spec(dct['offset'])
        dct['size'] = Size.from_spec(dct['size'])
        return cls(**dct)


class StringField(Field):
    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        self._position(obj)
        bs = obj.stream.read(self.sz_bits)
        return codecs.decode(bs.bytes, self.display or 'ascii')

    def __set__(self, obj, value):
        self._position(obj)
        obj.stream.overwrite(codecs.encode(s, self.display or 'ascii'))


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
            setattr(subclass, dct['fid'], Field.from_spec(dct))
        cls.registry[name] = subclass
        return subclass

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
