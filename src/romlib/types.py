import logging

from abc import ABCMeta


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
        offset_raw, sep, origin_raw = reversed(spec.partition(":"))

        if origin == 'rel' or not origin:
            origin = None
        elif origin == 'abs':
            origin = origin_raw
        else:
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
        if self.origin is not None:
            origin = self.origin
        else:
            origin = instance.parent.offset

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


class FieldType(abc.ABCMeta):
    def __new__(cls, name, bases, dct):
        unstring = {
                'offset': OffsetSpec,
                'size': SizeSpec,
                'mod': lambda m: util.intify(m, m),
                'order': lambda o: int(o) if o else 0,
                }

        for key, func in unstring.items():
            if key in dct and isinstance(key, str):
                dct[key] = func(dct[key])

        return super().__new__(cls, name, bases, dct)

class Field(metaclass=FieldType):
    registry = {}

    fid = abc.abstractproperty()
    type = abc.abstractproperty()
    offset = abc.abstractproperty()
    size = 8  # bits
    display = None
    mod = None
    order = 0
    comment = None

    def __init__(self, parent):
        self.parent = parent

    def __str__(self):
        return str(self.read())

    @property
    def sz_bits(self):
        """ Get the field's size in bits."""

        return self.size

    @property
    def sz_bytes(self):
        """ Get the field's size in bytes, if possible."""

        bits = self.sz_bits
        if bits % 8 != 0:
            raise ValueError("Not an even number of bytes")
        else:
            return bits // 8

    @abstractmethod
    def read(self):
        raise NotImplementedError

    @abstractmethod
    def write(self, value):
        raise NotImplementedError

    def __init_subclass__(cls, registry_key=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if registry_key:
            cls.registry[registry_key] = cls


class UInt(Field, "uint"):
    def read(self):
        stream = parent.stream
        bits = self.sz_bits
        offset = self.offset

        bsfmt = '{tp}:{sz}'.format(tp=self.type, sz=bits)
        stream.pos = offset
        return stream.read(bsfmt)

    def write(self, value):
        stream = parent.stream
        bits = self.sz_bits
        offset = self.offset

        bsfmt = '{tp}:{sz}={val}'.format(tp=self.type, sz=bits, val=value)
        stream.pos = offset
        stream.overwrite(bsfmt)


class Pointer(UInt, "ptr"):
    def __str__(self):
        return util.hexify(self.read(), self.sz_bytes)


class Bitfield(Field, "bin"):
    mod = 'msb0'
    _modfunc = {'msb0': lambda bs: bs,
                'lsb0': lambda bs: util.lbin_reverse(bs)}

    def __str__(self):
        return util.displaybits(bits, self.display)

    @property
    def modfunc(self):
        # Should really be a classproperty
        return self._modfunc[self.mod]

    def read(self):
        bs = super().read()
        return self.modfunc(bs)

    def write(self, bs):
        bs = self.modfunc(bs)
        super().write(bs)


class String(Field, "str"):
    display = 'ascii'

    def read(self):
        self.stream.pos = self.offset
        bs = self.stream.read(self.size.bytes)
        return codecs.decode(bs, self.display)

    def write(self, s):
        self.stream.pos = self.offset
        self.stream.overwrite(codecs.encode(s, self.display))


class StructType(type):
    registry = {}

    def __init_subclass__(cls, fields=None, **kwargs):
        super().__init_subclass__(**kwargs)

        # Create field containers for the subclass
        cls._fields = []
        cls._field_dict = {}
        cls._fields_by_id = {}
        cls._fields_by_label = {}

        # FIXME: somewhere around here we need to autopopulate field offsets
        for field in cls._coerce_fields(fields):
            cls._add_field(field)

        cls._register()

    def _coerce_fields(cls, fields):
        # Convert types if necessary
        for field in fields:
            if isinstance(f, FieldType):
                yield f
            else:
                yield FieldType(f)

    def _check_field_conflicts(cls, field):
        # check for name shadowing
        if field.fid in dir(cls):
            msg = "field id {}.{} shadows a built-in attribute"
            raise ValueError(msg.format(name, fid))

        # check for field name conflicts
        for name in field.fid, field.label:
            if name in cls._field_dict:
                msg = "duplicated field id or label: {}.{}"
                raise ValueError(msg.format(cls.__name__, name))

    def _add_field(cls, field):
        cls._check_field_conflicts(field)
        cls._fields.append(field)
        cls._field_dict[field.fid] = field
        cls._field_dict[field.label] = field
        cls._fields_by_id[field.fid] = field
        cls._fields_by_label[field.label] = field

    def _register(cls):
        if cls.__name__ in cls.registry:
            msg = "duplicate definition of '{}'"
            raise ValueError(msg.format(name))
        cls.registry[cls.__name__] = cls

    def __getitem__(cls, key):
        return self._field_dict[key]

    @property
    def fields(cls):
        return cls._fields


class StructInstance(abc.Mapping, metaclass=StructType):
    def __init__(self, stream, offset):
        # FIXME: Check behavior vs get/setattr
        self.stream = stream
        self.offset = offset
        self.data = {}
        for field in self.fields:
            fieldinstance = field(self)
            # We want to be able to look up data by either id or label
            self.data[datafield.fid] = fieldinstance
            self.data[datafield.label] = fieldinstance

    @property
    def fields(self):
        return type(self).fields

    def dump(self, use_labels=True):
        return {field.label if use_labels else field.fid: self[field.fid]
                for field in self.fields}

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
