import logging

from abc import ABCMeta


log = logging.getLogger(__name__)
registry = {}


def register(name, cls):
    if name in registry:
        raise ValueError("Duplicate custom type: " + name)
    registry[name] = cls


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

    def resolve(self, struct):
        if self.origin is not None:
            origin = self.origin
        else:
            origin = struct.offset

        if self.offset is not None:
            offset = self.offset
        else:
            offset = struct[self.sibling]

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

    def resolve(self, struct):
        if self.sibling is None:
            return self.count * self.scale
        else:
            return struct[self.sibling] * self.scale



class StructField(ABCMeta):
    def __init__(cls, name, bases, dct):
        # empty strings get stripped out; the parent class provides defaults
        dct = {k: v for k, v in dct.items() if v}

        # string values (e.g. as read from tsv) get made into objects as
        # necessary
        unstring = {
                'fid': s,
                'type': s,
                'desc': s,
                'display': s,
                'offset': OffsetSpec(s),
                'size':   SizeSpec(s),
                'mod':    lambda s: util.intify(s, s),
                'order':  lambda s: util.intify(s, 0),
                }
        for key, func in unstring.items():
            if key in dct and isinstance(dct[key], str):
                dct[key] = func(dct[key])

        super().__init__(name, bases, dct)


class InstanceField(metaclass=StructField):

    tid = None

    def __init__(self, parent)
        self.parent = parent
        self.stream = parent.stream

    def __str__(self):
        return str(self.read())

    @property
    def sz_bits(self):
        """ Get the field's size in bits."""

        return type(self).size.resolve(self.parent)

    @property
    def sz_bytes(self):
        if self.sz_bits % 8 != 0:
            raise ValueError("Not an even number of bytes")
        else:
            return sz_bits // 8

    @property
    def offset(self):
        """ Get the field's absolute offset within the rom stream """

        return type(self).offset.resolve(self.parent)

    def read(self):
        self.stream.pos = self.offset
        bsfmt = '{}:{}'.format(self.type, self.sz_bits)
        return self.stream.read(bsfmt)

    def write(self, value):
        self.stream.pos = self.offset_rom
        bsfmt = '{}:{}={}'.format(self.type, self.sz_bits, value)
        self.stream.overwrite(bsfmt)

    @classmethod
    def define(cls, name, spec):
        """ Do I really need this? """
        return type(name, (cls,), spec)


class Pointer(InstanceField):
    tid = 'ptr'

    def __str__(self):
        fmtstr = '0x{{:0{}X}}'.format(self.sz_bytes)
        return fmtstr.format(self.read())


class Bitfield(InstanceField):
    _modfunc = {'msb0': lambda bs: bs,
                'lsb0': lambda bs: util.lbin_reverse(bs)}
    tid = 'bin'
    mod = 'msb0'
    modfunc = _modfunc[mod]

    def __str__(self):
        return util.displaybits(bits, self.display)

    def read(self):
        bs = super().read()
        return self.modfunc(bs)

    def write(self, bs):
        bs = self.modfunc(bs)
        super().write(bs)


class String(InstanceField):
    tid = 'str'
    display = 'ascii'
    _last_read_size = None

    def read(self):
        self.stream.pos = self.offset.resolve(self.parent)
        bs = self.stream.read(self.size.bytes)
        return codecs.decode(bs, self.display)

    def write(self, s):
        self.stream.pos = self.offset.resolve(self.parent)
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
    def define(cls, name, field_specs):
        bases = (cls,)
        clsdct = {field['id']: field for field in field_specs}
        return type(name, bases, clsdict)
