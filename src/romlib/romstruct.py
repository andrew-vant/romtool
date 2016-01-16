"""This module contains classes for manipulating binary structures in ROMs."""

from collections import OrderedDict

from bitstring import *

from . import util


class Struct(object):
    """ Base class for ROM structures -- mostly table entries.

    Subclasses should override the class variables below; they specify
    the fields of a given structure type.
    """
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
    def from_bitstream(cls, bs, offset=None):
        """ Read in a new structure from a bitstream.

            `bs` must be a BitStream or ConstBitStream. If offset is provided,
            it must be specified in bits and reading will begin from there.
            Otherwise, reading will begin from bs.pos.
        """
        if offset is not None:
            bs.pos = offset
        data = {field.id: field.from_bitstream(bs)
                for field in cls._data}
        for field in cls._links:
            pointer = cls._fields[field.pointer]
            bs.pos = (data[pointer.id] + pointer.mod) * 8
            data[field.id] = field.from_bitstream(bs)
        return Struct(data)

    @classmethod
    def from_file(cls, f, offset=None):
        """ Read in a new structure from a file object

        `f` must be a file object opened in binary mode. If offset is provided,
        it must be specified in bytes and reading will begin from there.
        Otherwise, reading will begin from f.tell()
        """
        if offset is None:
            offset = f.tell()
        bit_offset = offset * 8
        bs = ConstBitStream(f)
        return cls.from_bitstream(bs, bit_offset)

    def changeset(self, f=None, offset=None):
        """ Get an offset-to-byte-value dict.

        If file object `f` is provided, the dict will be filtered such that
        bytes that do not need to be changed will not be included.

        `offset` indicates the starting point of the structure. If omitted, it
        will default to f.tell() if f was provided or 0 if it was not.
        """

        changes = {}
        # Deal with regular data fields first. These are expected to all be
        # bitstring-supported types because I've yet to see a ROM that wasn't
        # that way.
        if offset is None:
            offset = f.tell() if f is not None else 0
        bs = BitStream()
        for field in self._data:
            value = getattr(self, field.id)
            bs.append(field.to_bits(value))
        for i, byte in enumerate(bs.bytes):
            changes[offset+i] = byte

        # Deal with pointers.
        for field in self._links:
            value = getattr(self, field.id)
            offset = getattr(self, field.pointer)
            bits = field.to_bits(value)
            for i, byte in enumerate(bits.bytes):
                changes[offset+i] = byte

        # Filter the changes against `f` if necessary.
        if f is not None:
            for offset, byte in changes.items():
                f.seek(offset)
                oldval = int.from_bytes(f.read(1), 'little')
                if oldval == byte:
                    del changes[offset]

        # Done
        return changes

    @staticmethod
    def dictify(*romstructs):
        """ Turn a set of structures into an ordereddict for serialization.

        The odict will contain all their values and be ordered in a sane manner
        for outputting to (for example) csv). All values will be converted to
        string.

        They must not have overlapping ids/labels.
        """

        data = []
        for i, rst in enumerate(romstructs):
            for field in rst._fields:
                key = field.label if field.label else field.id
                value = field.stringify(getattr(rst, field.id))
                ordering = field.fullorder(i)
                data.append(key, value, ordering)

        data.sort(key=lambda d: d[-1])
        return OrderedDict(d[:2] for d in data)


class Field(object):  # pylint: disable=too-many-instance-attributes
    """ An individual field of a structure.

    For example, a 3-byte integer or a delimiter-terminated string.
    """
    def __init__(self, odict, ttable=None, available_tts=None):
        self.id = odict['id']  # pylint: disable=invalid-name
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
        # FIXME: should probably raise an exception if someone asks for a
        # string type without a text table.
        if ttable is None and available_tts is not None:
            ttable = available_tts[self.display]
        self.ttable = ttable

    def from_file(self, f, offset=None):
        """ Read a field from a byte offset within a file.

        Obviously this only works if a field starts somewhere byte-aligned. If
        `offset` is not provided, it will be read from f.tell().

        The returned value will be a string or an int, as appropriate.
        """
        if offset is None:
            offset = f.tell()
        bitoffset = offset * 8
        bs = ConstBitStream(f)
        return self.from_bitstream(bs, bitoffset)

    def from_bitstream(self, bs, offset=None):
        """ Read a field from a bit offset within a bitstream.

        If `offset` is not provided, bs.pos will be used.

        The returned value will be a string or an int, as appropriate.
        """
        if offset is not None:
            bs.pos = offset

        if self.type == "strz":
            # FIXME: Pretty sure this won't work.
            return self.ttable.readstr(bs)
        else:
            try:
                fmt = "{}:{}".format(self.type, self.bitsize)
                return bs.read(fmt)
            except ValueError:
                msg = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(msg, self.id, self.type)


    def to_bits(self, value):
        """ Convert a value to a Bits object."""
        if self.type == "strz":
            return Bits(self.ttable.encode(value))
        else:
            return Bits("{}:{}={}".format(self.type, self.size, value))

    def to_bytes(self, value):
        """ Convert a value to a bytes object.

        This may fail if the field is not a whole number of bytes long.
        """
        return self.to_bits(value).bytes

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
    fields = []
    for fdef in fdefs:
        if isinstance(fdef, Field):
            fields.append(fdef)
        else:
            fields.append(Field(fdef, available_tts=texttables))

    clsvars = {
        '_fields': fields,
        '_links': [f for f in fields if f.pointer],
        '_data': [f for f in fields if not f.pointer],
        }

    cls = type(name, (Struct,), clsvars)
    return cls
