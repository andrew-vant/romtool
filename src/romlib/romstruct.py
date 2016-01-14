import bitstring

# No package for python3 bunch in debian/ubuntu, preferable not to depend on it.

from bunch import *
from collections import namedtuple

from . import text
from . import util


_type_registry = Bunch()


class RomStruct(object):
    # Subclasses should override this.
    _fields = OrderedDict()
    def __init__(self, d):
        self.links = Bunch()
        self._datafields = [f for f in _fields if not f.id.startswith('*')]
        self._linkfields = [f for f in _fields if f.id.startswith('*')]

        for field in self._datafields:
            value = d.get(field.id, d[field.label])
            setattr(self, field.id, value)
        for field in self._linkfields:
            value = d.get(field.id, d[field.label])
            self.links[field.id[1:]] = value

    @classmethod
    def from_bs(cls, bs, bitoffset=None):
        if bitoffset is not None:
            bs.pos = bitoffset
        d = {field.id: field.read_bs(bs, None)
             for field in _fields
             if not fid.startswith('*')}
        for field in _fields:
            if field.id.startswith('*'):
                pointer = field[fid[1:]]
                pos = d[pointer.id] - pointer.pzero * 8
                d[field.id] = field.read_bs(bs, pos)
        return RomStruct(d)


    @staticmethod
    def dictify(*structures):
        """ Turn a set of structures into an ordereddict for serialization.

        The dict will contain all their values and be ordered in a sane manner
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

        data = sorted(data, lambda d: d[-1])
        return OrderedDict(d[:2] for d in data)

    def dictify(self):
        pass


class Field(object):
    def __init__(self, odict):
        self.id = odict['id']
        self.label = odict['label']
        self.size = util.tobits(odict['size'])
        self.type = odict['type']
        self.display = odict['display']
        self.order = int(odict['order'])
        # Still don't know how pzero should be done...
        self.pzero = int(odict['pzero'])
        self.info = odict['info']
        self.comment = odict['comment']

        # Utility properties not in input
        self.bytesize = util.tobytes(self.size)
        self.bitsize = util.tobits(self.size)

    def read_bs(self, bs, bitoffset=None):
        if self.type == "strz":
            return text.tables[self.display].readstr_bs(bs, bitoffset)
        elif self.type in _type_registry:
            o = _type_registry[self.type]
            return o.from_bs(bs, bitoffset)
        else:
            try:
                if bitoffset is not None:
                    bs.pos = bitoffset
                fmtstr = "{}:{}".format(self.type, self.bitsize)
                return stream.read(fmt)
            except ValueError:
                s = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(s, self.id, self.type)

    def read_fileesque(self, f, byteoffset=None):
        bitoffset = None if byteoffset is None else byteoffset*8
        self.read_bs(ConstBitStream(f), bitoffset)

    def fullorder(self, origin_sequence_order=0):
        # Sort order priority is name, order given in definition,
        # pointer/nonpointer, binary order of field.
        nameorder = 0 if self.label == "Name" else 1
        typeorder = 1 if self.id.startswith("*") else 0
        return nameorder, self.order, typeorder, origin_sequence_order

    def stringify(value):
        formats = {
            'pointer': '0x{{:0{}X}}'.format(self.bytesize*2),
            'hex': '0x{{:0{}X}}'.format(self.bytesize*2)
            }
        fstr = formats.get(self.display, '{}')
        return fstr.format(value)

    def unstringify(s):
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
    fields = [Field(od) for od in odicts]
    cls = type(name, (RomStruct,), {'_fields': fields})
    _type_registry[name] = cls
    return cls
