import logging


log = logging.getLogger(__name__)
registry = {}


def register(name, cls):
    if name in registry:
        raise ValueError("Duplicate custom type: " + name)
    registry[name] = cls


class RomObject(metaclass=RomObjectType):
    pass

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
        offset, sep, origin = reversed(spec.partition(":"))

        if origin == 'rel' or not origin:
            self.relative = False
        elif origin == 'abs':
            self.relative = True
        else:
            raise ValueError("Invalid offset spec: " + spec)

        try:
            self.offset = int(offset, 0)
            self.sibling = None
        except (ValueError, TypeError):
            self.offset = None
            self.sibling = offset

    def resolve(self, parent=None):
        offset = self.offset if not self.sibling else parent[self.sibling]
        if self.relative:
            offset += parent.offset
        return offset


class PrimitiveType():
    def __init__(cls, name, bases, dct):
        # empty strings get stripped out; the parent RomObject class
        # provides defaults.
        dct = {k: v for k, v in dct.items() if v}
        cls.sz_bits = util.tobits(dct['size'], None)

        # Uncast string values get cast
        unstring = {
                'size': lambda s: util.tobits(s, 0),
                'order': lambda s: util.intify(s),
                'mod': lambda s: util.intify(s, s)
                }

        for key, func in unstring.items():
            if key in dct and isinstance(dct[key], str):
                dct[key] = func(dct[key])

        # Note bitstring format string for this type.
        dct['rfmt'] = '{}:{}'.format(dct['type'], dct['size'])
        dct['wfmt'] = dct['rfmt'] + '={}'

        super().__init__(name, bases, dct)


class Primitive(metaclass=PrimitiveType):
    # Mandatory fields included here for documentation
    _offset = None
    size = None
    mod = None

    def __init__(self, parent, offset, fmt):
        self.parent = parent
        self.stream = parent.stream

    def __str__(self):
        return str(self.read())

    @property
    def offset(self):
        return self._offset.resolve(self.parent)

    @property
    def sz_bits(self):


    def read(self):
        self.stream.pos = self.offset
        return self.stream.read(self.fmt)

    def write(self, value):
        self.stream.pos = self.offset
        self.stream.overwrite(self.wfmt.format(value))

    @classmethod
    def define(cls, name, spec):
        """ Do I really need this? """
        return type(name, (cls,), spec)


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
