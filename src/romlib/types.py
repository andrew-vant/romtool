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
    registry = {}

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
    tid = abc.abstractproperty()

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


class UInt(Field):
    tid = 'uint'
    type = 'uint'


class PointerField(UInt):
    tid = 'ptr'

    def __str__(self):
        return util.hexify(self.read(), self.sz_bytes)


class BitfieldField(Field):
    tid = 'bin'
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


class String(Field):
    tid = 'str'
    display = 'ascii'

    def read(self):
        self.stream.pos = self.offset
        bs = self.stream.read(self.size.bytes)
        return codecs.decode(bs, self.display)

    def write(self, s):
        self.stream.pos = self.offset
        self.stream.overwrite(codecs.encode(s, self.display))


class StructType(type):
    def __init__(cls, name, bases, dct, fieldspecs):
        fields = []
        by_id = {}
        by_label = {}

        for spec in fieldspecs:
            # Get the relevant field attributes
            fid = spec['id']
            fname = name + "." + fid
            flabel = spec.get('label', fid)
            fbase = registry.get(spec['type'], Primitive)

            # Sanity checks
            if fid in by_id:
                msg = "duplicate field id: {}.{}"
                raise ValueError(msg, name, fid)
            if flabel in by_label:
                msg = "duplicate field label: {}[{}]"
                raise ValueError(msg, name, flabel)
            if fid in dir(cls):
                msg = "field id {}.{} shadows a built-in attribute"
                raise ValueError(msg, name, fid)

            # Create field type
            ftype = type(fid, (fbase, ), spec)
            fields.append(ftype)
            by_id[fid] = ftype
            by_label[flabel] = ftype

        dct.update({'fields': fields,
                    'fld_by_id': by_id,
                    'fld_by_label': by_label})

        super().__init__(name, bases, dct)
        register(cls)


class Structure(metaclass=StructType):
    def __init__(self, stream, offset):
        # FIXME: Check behavior vs get/setattr
        self.stream = stream
        self.offset = offset
        self.fields = {fld.id: fld(

    def __str__(self):
        return yaml.dump(self.fields)

    def _fld_offset(self, field):
        return self.offset + self.fields[field].offset

    def __getattr__(self, key):
        fld = self.fields[key]
        self.stream.pos = self.offset + fld.offset
        return self.stream.read("{}:{}".format(fld.type, fld.size))

    def __setattr__(self, key, value):
        pass

    def __getitem__(self, key):
        # Get the offset of the item within the stream; read it.


    def __setitem__(self, key, value):
        self.fields[key].write(value)

    @classmethod
    def __init_subclass__(cls):
        # register the subclass somehow? Or at least log it.
        return super().__init_subclass(cls)

    @classmethod
    def define(cls, name, field_specs):
        bases = (cls,)
        clsdct = {field['id']: field for field in field_specs}
        return type(name, bases, clsdict)
