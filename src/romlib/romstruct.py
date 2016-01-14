from collections import OrderedDict

from bitstring import ConstBitStream, BitStream, Bits

from . import text
from . import util

class Registry():
    # Note, functions are all prepended with _, and structure names may not
    # start with _. This is to prevent accidentally overwriting methods.
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def _register(self, stype):
        name = stype.__name__
        if name.startswith('_'):
            raise ValueError("Struct names may not start with '_'. Don't be evil.")
        setattr(self, name, stype)

_type_registry = Registry()

class RomStruct(object):
    # Subclasses should override this. Data and links might be a good use case
    # for a metaclass.
    _fields = OrderedDict()  # All fields in the struct.
    _data = OrderedDict()    # Fields that are physically part of the struct.
    _links = OrderedDict()   # Fields that are pointed to by another field.

    def __init__(self, d):
        """Create a new structure from a dictionary.

        The structure's fields will be initialized from the corresponding items
        in the dictionary. They dictionary may be keyed by either the field id
        or the field label. The field id is checked first. Superfluous items
        are ignored. If the values are strings of non-string types, as when
        read from a .csv, they will be converted.
        """
        for field in self._fields.values():
            # Look for fields both by id and by label.
            value = d.get(field.id, d[field.label])
            if isinstance(value, str) and 'int' in field.type:
                value = int(value, 0)
            setattr(self, field.id, value)

    @classmethod
    def read(cls, source):
        bs = ConstBitStream(source)
        d = {field.id: field.read(bs)
             for field in cls._data}
        for field in cls._links:
            pointer = cls._fields[field.pointer]
            bs.pos = (d[pointer.id] + pointer.mod) * 8
            d[field.id] = field.read(bs)
        return RomStruct(d)

    @staticmethod
    def dictify(*structures):
        """ Turn a set of structures into an ordereddict for serialization.

        The odict will contain all their values and be ordered in a sane manner
        for outputting to (for example) csv). All values will be converted to
        string.

        They must not have overlapping ids/labels.
        """

        data = []
        for i, s in enumerate(structures):
            for field in s._fields:
                target = s if field in s._datafields else s.links
                key = field.label if field.label else field.id
                value = field.stringify(getattr(target, field.id))
                ordering = field.fullorder(i)
                data.append(key, value, ordering)

        data.sort(key=lambda d: d[-1])
        return OrderedDict(d[:2] for d in data)


class Field(object):
    def __init__(self, odict):
        self.id = odict['id']
        self.label = odict['label']
        self.size = util.tobits(odict['size'])
        self.type = odict['type']
        self.display = odict['display']
        self.order = int(odict['order'])
        self.pointer = odict['pointer'] if odict['pointer'] else None
        self.mod = int(odict['mod'])
        self.info = odict['info']
        self.comment = odict['comment']

        # Utility properties not in input
        self.bytesize = util.tobytes(self.size)
        self.bitsize = util.tobits(self.size)

    def read(self, source):
        """ Read a field from some data source and return its value.

        `source` may be any type that can be used to initialize a
        CostBitStream. If it is a file object or bitstream, it must be set to
        the appropriate start position before this method is called (e.g. with
        file.seek() or bs.pos). The object returned will be an integer, string,
        or struct, as appropriate.
        """
        bs = ConstBitStream(source)  # FIXME: Does this lose a file's seek pos?
        if self.type == "strz":
            return text.tables[self.display].readstr(bs)
        elif hasattr(_type_registry, self.type):
            o = getattr(_type_registry, self.type)
            return o.read(bs)
        else:
            try:
                fmt = "{}:{}".format(self.type, self.bitsize)
                return bs.read(fmt)
            except ValueError:
                s = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(s, self.id, self.type)

    def write(self, dest, value):
        """ Write a field to some data destination.

        `dest` may be any type that can be used to initialize a BitStream. If
        it is a file object or bitstream, it must be set to the appropriate
        start position before this method is called.
        """
        bs = BitStream(dest)
        if self.type == "strz":
            bs.overwrite(Bits(text.tables[self.display].encode(value)))
        elif hasattr(_type_registry, self.type):
            raise NotImplementedError("Nested structs not implemented yet.")
        else:
            bits = Bits('{}:{}={}'.format(self.type, self.size, value))
            bs.overwrite(bits)

    def fullorder(self, origin_sequence_order=0):
        # Sort order priority is name, order given in definition,
        # pointer/nonpointer, binary order of field.
        nameorder = 0 if self.label == "Name" else 1
        typeorder = 1 if self.id.startswith("*") else 0
        return nameorder, self.order, typeorder, origin_sequence_order

    def stringify(self, value):
        # FIXME: doesn't work for substructs, but we don't have those yet.
        formats = {
            'pointer': '0x{{:0{}X}}'.format(self.bytesize*2),
            'hex': '0x{{:0{}X}}'.format(self.bytesize*2)
            }
        fstr = formats.get(self.display, '{}')
        return fstr.format(value)

    def unstringify(self, s):
        try:
            return int(s, 0)
        except ValueError:
            return s


def define(name, auto):
    """ Define a new structure type.

    `auto` should be an iterable. It may contain either Field objects or any
    type that can be used to initialize a Field object (usually dicts).

    The new type will be registered and can be accessed with
    romlib.structures.<typename>
    """

    fields = [Field(a) if not isinstance(a, Field) else a
              for a in auto]
    clsvars = {
        '_fields': fields,
        '_links': [f for f in fields if f.pointer],
        '_data': [f for f in fields if not f.pointer]
        }

    cls = type(name, (RomStruct,), clsvars)
    _type_registry._register(cls)
    return cls
