import logging


log = logging.getLogger(__name__)
registry = {}

def register(name, cls):
    if name in registry:
        raise ValueError("Duplicate custom type: " + name)
    registry[name] = cls


class PrimitiveType(type):
    def __init__(cls, name, bases, dct):
        # empty strings get stripped out; the parent provides defaults.
        for k, v in dct.copy().items():
            if v == "":
                del(dct[k])

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
    def __init__(self, parent, offset):
        self.stream = parent.stream
        self.offset = offset

    def __str__(self):
        return str(self.read())

    def read(self):
        self.stream.pos = parent.offset + self.offset
        return self.string.read(self.rfmt)

    def write(self, value):
        self.stream.pos = parent.offset + self.offset
        self.stream.overwrite(self.wfmt.format(value))

    @classmethod
    def define(cls, name, spec):
        """ Do I really need this? """
        return type(name, (cls,), spec)


class FieldSpecs:
    """ Convenience container for field specs

    Allows lookup in order, by ID, or by label """
    pass  # TODO



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

        offset = 0
        self.fields = {}
        for fid, ftype in self.fld_by_id.items():
            self.fields[fid] = ftype(self, offset)
            offset += ftype.offset

    def __str__(self):
        return yaml.dump(self.fields)

    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value

    def __getitem__(self, key):
        return self.fields[key].read()

    def __setitem__(self, key, value):
        self.fields[key].write(value)

    @classmethod
    def define(cls, name, field_specs):
        bases = (cls,)
        clsdct = {field['id']: field for field in field_specs}
        return type(name, bases, clsdict)
