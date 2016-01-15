from collections import OrderedDict

from bitstring import ConstBitStream, BitStream, Bits

from . import util


class RomStruct(object):
    """ Base class for ROM structures -- mostly table entries.

    Subclasses should override the three class variables below; they specify
    the fields of a given structure type.
    """
    _fields = OrderedDict()  # All fields in the struct.
    _data = OrderedDict()    # Fields that are physically part of the struct.
    _links = OrderedDict()   # Fields that are pointed to by another field.
    _codecs = dict()         # Text tables to be used for string conversions.

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
        """ Read in a new structure from a given source.

        `source` may be a ConstBitStream or any type that can be used to
        initialize one. If it is a file or bitstream, it must have the read
        position set via seek() or .pos before calling this.
        """
        bs = ConstBitStream(source)
        data = {field.id: field.read(bs)
                for field in cls._data}
        for field in cls._links:
            pointer = cls._fields[field.pointer]
            bs.pos = (data[pointer.id] + pointer.mod) * 8
            data[field.id] = field.read(bs)
        return RomStruct(data)

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
    """ An individual field of a structure.

    For example, a 3-byte integer or a delimiter-terminated string.
    """
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
        self.bitsize = util.tobits(odict['size'])
        self.bytesize = util.divup(self.bitsize, 8)

    def read(self, source, ttables=None, default_tt=None):
        """ Read a field from some data source and return its value.

        `source` may be any type that can be used to initialize a
        CostBitStream. If it is a file object or bitstream, it must be set to
        the appropriate start position before this method is called (e.g. with
        file.seek() or bs.pos). The object returned will be an integer or
        string, as appropriate.
        """
        if ttables is None:
            ttables = {}
        bs = ConstBitStream(source)  # FIXME: Does this lose a file's seek pos?
        if self.type == "strz":
            ttable = ttables.get(self.display, default_tt)
            return ttable.readstr(bs)
        else:
            try:
                fmt = "{}:{}".format(self.type, self.bitsize)
                return bs.read(fmt)
            except ValueError:
                msg = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(msg, self.id, self.type)

    def write(self, dest, value, ttables=None, default_tt=None):
        """ Write a field to some data destination.

        `dest` may be any type that can be used to initialize a BitStream. If
        it is a file object or bitstream, it must be set to the appropriate
        start position before this method is called.
        """
        if ttables is None:
            ttables = {}
        bs = BitStream(dest)
        if self.type == "strz":
            ttable = ttables.get(self.display, default_tt)
            bs.overwrite(Bits(ttable.encode(value)))
        else:
            bits = Bits('{}:{}={}'.format(self.type, self.size, value))
            bs.overwrite(bits)

    def fullorder(self, origin_sequence_order=0):
        """ Get the sort order of this field.

        This returns a tuple containing several properties relevant to sorting.
        Sort order is name, order given in definition, pointer/nonpointer
        (pointers go last), and the binary order of the field.

        This is done with a function rather than greater/less than because the
        field object doesn't actually know its binary order and needs to have
        it provided.
        """
        nameorder = 0 if self.label == "Name" else 1
        typeorder = 1 if self.info == "pointer" else 0
        return nameorder, self.order, typeorder, origin_sequence_order

    def stringify(self, value):
        """ Convert `value` to a string.

        Note that we don't use the `str` builtin for this because some fields
        ought to have specific formatting in the output -- e.g. pointers should
        be a hex string padded to cover their width.
        """
        formats = {
            'pointer': '0x{{:0{}X}}'.format(self.bytesize*2),
            'hex': '0x{{:0{}X}}'.format(self.bytesize*2)
            }
        if self.mod:
            value += self.mod
        fstr = formats.get(self.display, '{}')
        return fstr.format(value)

    def unstringify(self, s):  # pylint: disable=invalid-name
        """ Convert the string `s` to an appropriate value type."""
        value = None
        if 'int' in self.type:
            value = int(s, 0)
        else:
            value = s
        if self.mod:
            value -= self.mod
        return value

def define(name, fdefs, texttables):
    """ Create a new structure type.

    `fdefs` should be an iterable. It may contain either Field objects or any
    type that can be used to initialize a Field object (usually dicts).
    """

    fields = [Field(fd) if not isinstance(fd, Field) else fd
              for fd in fdefs]
    clsvars = {
        '_fields': fields,
        '_links': [f for f in fields if f.pointer],
        '_data': [f for f in fields if not f.pointer],
        '_codecs': {tt.name: tt for tt in texttables}
        }

    cls = type(name, (RomStruct,), clsvars)
    return cls
