import logging

import abc


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


class Field:
    primitives = {}

    fid = abc.abstractproperty()
    type = abc.abstractproperty()
    offset = abc.abstractproperty()
    size = 8  # bits
    display = None
    mod = None
    order = 0
    comment = None

    @classmethod
    def __init_subclass__(cls, register=None, **kwargs):
        if register in cls.primitives:
            raise ValueError(f"primitive registered twice: {register}")
        elif register:
            cls.primitives[register] = cls

    @classmethod
    def define(cls, parent_name, spec):
        """ define a new field type from a stringdict """

        # Figure out the appropriate class name
        name = parent_name + '.' + spec['fid']

        # Get the base class from the registry
        base_key = spec['type']
        if base_key not in cls.base_registry:
            raise ValueError(f"{name}: unknown field type '{base_key}'")
        else:
            base = cls.base_registry[base_key]

        # convert attributes if needed
        funcs = {'offset': OffsetSpec,
                 'size': SizeSpec,
                 'order': int}
        spec = util.unstring(spec, funcs, True)

        # Make and return
        return type(name, (base,), spec)

    def __init__(self, parent):
        self.parent = parent

    def __str__(self):
        return str(self.read())

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

    @property
    def stream(self):
        return self.parent.stream

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


class UInt(Field, register="uint"):
    mod = 0

    def __str__(self):
        val = self.read()
        if self.display == 'hex':
            return util.hexify(val, self.sz_bytes)
        else:
            return str(val)

    @classmethod
    def define(cls, parent_name, spec):
        spec = util.unstring(spec, {'mod': int}, True)
        return super().define(parent_name, spec)


class Pointer(Field, register="ptr"):
    def __str__(self):
        return util.hexify(self.read(), self.sz_bytes)


class String(Field, register="str"):
    def read(self):
        self.stream.pos = self.offset
        bs = self.stream.read(self.sz_bytes)
        return codecs.decode(bs, self.display or 'ascii')

    def write(self, s):
        self.stream.pos = self.offset
        self.stream.overwrite(codecs.encode(s, self.display or 'ascii'))


class Bitfield(Field, register="bin"):
    mod = 'msb0'

    def __str__(self):
        return util.displaybits(self.read(), self.display)

    def read(self):
        self.stream.pos = self.offset
        bs = self.stream.read(self.sz_bits)
        if self.mod == 'lsb0':
            bs = util.lbin_reverse(bs)

    def write(self, bs):
        self.stream.pos = self.offset
        self.stream.overwrite(bs)


class Structure:
    registry = {}

    # fields should be a list of Field subclasses. They will be used to
    # instantiate instance data when Structure itself is instantiated.
    fields = []

    def __init__(self, stream, offset):
        # FIXME: Check behavior vs get/setattr
        self.stream = stream
        self.offset = offset
        self.data = {}
        for fieldcls in self.fields:
            field = fieldcls(self)
            # We want to be able to look up data by either id or label
            self.data[datafield.fid] = fieldinstance
            self.data[datafield.label] = fieldinstance

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

        # Create field lookup tables
        cls.fields.by_id = {f.fid: f for f in cls.fields}
        cls.fields.by_label = {f.label: f for f in cls.fields}
        cls.fields.by_any = {**_fields_by_id, **fields_by_label}

        # Register the structure type
        if cls.__name__ in cls.registry:
            raise ValueError(f"duplicate definition of '{cls.__name__}'")
        cls.registry[name] = cls

    @classmethod
    def define(cls, name, field_dicts):
        """ Define a type of structure from a list of stringdicts

        The newly-defined type will be registered and also returned.
        """

        fields = [Field.define(name, dct)
                  for dct in field_dicts]
        struct_subclass = type(name, (cls,), {'fields': fields})
        cls.registry[name] = struct_subclass
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
