"""This module contains classes for manipulating binary structures in ROMs."""

from collections import OrderedDict
from types import SimpleNamespace

from bitstring import *

from . import util


class StructDef(object):
    def __init__(self, name, fdefs, texttables=None):
        """ Create a new structure type.

        *fdefs* should be an iterable. It may contain either Field objects or any
        type that can be used to initialize a Field object (usually dicts).
        """
        # FIXME: raise an exception for a structure for which the main data
        # members don't sum to a whole-byte size.
        if texttables is None:
            texttables = {}

        fields = OrderedDict()
        for fdef in fdefs:
            if not isinstance(fdef, Field):
                fdef = Field(fdef, available_tts=texttables)
            fields[fdef.id] = fdef

        self.fields = fields
        self.links = [f for f in fields if f.pointer]
        self.data = [f for f in fields if not f.pointer]
        self.cls = type(name, (SimpleNamespace,), {"_sdef": self})

    def from_dict(self, d):  # pylint: disable=invalid-name
        """Create a new structure from a dictionary.

        The structure's fields will be initialized from the corresponding items
        in the dictionary. They dictionary may be keyed by either the field id
        or the field label. The field id is checked first. Superfluous items
        are ignored. If the values are strings of non-string types, as when
        read from a .csv, they will be converted.
        """
        initializers = dict()
        for field in self.fields.values():
            # Look for fields both by id and by label.
            value = d.get(field.id, d[field.label])
            if isinstance(value, str):
                value = field.from_string(value)
            initializers[field.id] = value
        return self.cls(**initializers)

    def from_bitstream(self, bs, offset=None):
        """ Read in a new structure from a bitstream.

            bs must be a BitStream or ConstBitStream. If offset is provided,
            it must be specified in bits and reading will begin from there.
            Otherwise, reading will begin from bs.pos.
        """
        if offset is not None:
            bs.pos = offset
        data = {field.id: field.from_bitstream(bs)
                for field in self.data}
        for field in self.links:
            pointer = self.fields[field.pointer]
            bs.pos = (data[pointer.id] + pointer.mod) * 8
            data[field.id] = field.from_bitstream(bs)
        return self.cls(**data)

    def from_file(self, f, offset=None):
        """ Read in a new structure from a file object

        *f* must be a file object opened in binary mode. If offset is provided,
        it must be specified in bytes and reading will begin from there.
        Otherwise, reading will begin from f.tell()
        """
        if offset is None:
            offset = f.tell()
        bit_offset = offset * 8
        bs = ConstBitStream(f)
        return self.from_bitstream(bs, bit_offset)

    def to_bytemap(self, struct, offset=0):
        """ Get an offset-to-byte-value dict.

        Offset indicates the start point of the structure.
        """
        changes = {}
        # Deal with regular data fields first. These are expected to all be
        # bitstring-supported types because I've yet to see a ROM that wasn't
        # that way. For now the main data of the structure must be of
        # whole-byte size.
        bs = BitStream()
        for field in self.data:
            value = getattr(struct, field.id)
            bs.append(field.to_bits(value))
        for i, byte in enumerate(bs.bytes):
            changes[offset+i] = byte

        # Deal with pointers. For now pointers require whole-byte values.
        # Note that we no longer care about the struct's start point so we can
        # reuse offset.
        for field in self.links:
            value = getattr(struct, field.id)
            offset = getattr(struct, field.pointer)
            for i, byte in enumerate(field.to_bytes(value)):
                changes[offset+i] = byte

        # Done
        return changes

    def to_odict(self, struct, stringify=True, use_labels=True):
        """ Get an ordered dictionary of the structure's data.

        By default, the field labels will be used as keys if available, and all
        values will be converted to strings. The returned OrderedDict is
        suitable for sending to a csv or similar.
        """
        return StructDef.to_mergedict([struct], stringify, use_labels)

    @staticmethod
    def to_mergedict(structures, stringify=True, use_labels=True):
        """ Turn a list of structures into an ordereddict for serialization.

        The odict will contain all their values and be ordered in a sane manner
        for outputting to (for example) csv. By default, field labels will be
        used as keys if available, and values will be converted to strings.

        None of the structures may have overlapping field ids/labels.
        """

        data = []
        for i, struct in enumerate(structures):
            for field in struct._sdef.fields:
                key = field.label if field.label and use_labels else field.id
                value = getattr(struct, field.id)
                if stringify:
                    value = field.to_string(value)
                ordering = field.fullorder(i)
                data.append(key, value, ordering)

        data.sort(key=lambda d: d[-1])
        return OrderedDict(d[:2] for d in data)


class Field(object):  # pylint: disable=too-many-instance-attributes
    """ An individual field of a structure.

    For example, a 3-byte integer or a delimiter-terminated string. Most of the
    methods of Field are intended to transport value types to and from strings,
    bitstreams, file objects, etc.
    """
    # FIXME: doesn't need an odict input, regular dict works and shouldn't this
    # use individual values and have a from_dict constructor instead?
    def __init__(self, odict, ttable=None, available_tts=None):
        self.id = odict['id']  # pylint: disable=invalid-name
        self.label = odict['label']
        self.size = util.tobits(odict['size'])
        self.bitsize = util.tobits(odict['size'])
        self.bytesize = util.divup(self.bitsize, 8)
        self.type = odict['type']
        self.display = odict['display']
        self.order = int(odict['order'])
        self.pointer = odict['pointer'] if odict['pointer'] else None
        self.mod = int(odict['mod'], 0) if odict['mod'] else 0
        self.info = odict['info']
        self.comment = odict['comment']

        # FIXME: should probably raise an exception if someone asks for a
        # string type without a text table.
        if ttable is None and available_tts is not None:
            ttable = available_tts[self.display]
        self.ttable = ttable

    def from_bytes(self, data, offset=0):
        """ Read a field from within a bunch of bytes."""
        bitoffset = offset * 8
        bs = ConstBitStream(data)
        return self.from_bitstream(bs, bitoffset)

    def from_file(self, f, offset=None):
        """ Read a field from a byte offset within a file.

        Obviously this only works if a field starts somewhere byte-aligned. If
        *offset* is not provided, it will be read from f.tell().

        The returned value will be a string or an int, as appropriate.
        """
        if offset is None:
            offset = f.tell()
        bitoffset = offset * 8
        bs = ConstBitStream(f)
        return self.from_bitstream(bs, bitoffset)

    def from_bitstream(self, bs, offset=None):
        """ Read a field from a bit offset within a bitstream.

        If *offset* is not provided, bs.pos will be used.

        The returned value will be a string or an int, as appropriate.
        """
        if offset is not None:
            bs.pos = offset

        if 'str' in self.type:
            maxbits = self.bitsize if self.bitsize else 1024*8
            pos = bs.pos
            data = bs[pos:pos+maxbits]
            return self.ttable.decode(data.bytes)
        else:
            try:
                fmt = "{}:{}".format(self.type, self.bitsize)
                return bs.read(fmt)
            except ValueError:
                msg = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(msg, self.id, self.type)

    def from_string(self, s):  # pylint: disable=invalid-name
        """ Convert the string *s* to an appropriate value type."""
        if self.type in ['str', 'strz', 'bin', 'hex']:
            return s
        elif 'int' in self.type:
            return int(s, 0) - self.mod
        elif 'float' in self.type:
            return float(s) - self.mod
        else:
            msg = "Destringification of '{}' not implemented."
            raise NotImplementedError(msg, self.type)

    def to_bits(self, value):
        """ Convert a value to a Bits object."""
        if 'str' in self.type:
            return Bits(self.ttable.encode(value))
        else:
            init = {self.type: value, 'length': self.bitsize}
            return Bits(**init)

    def to_bytes(self, value):
        """ Convert a value to a bytes object.

        This may fail if the field is not a whole number of bytes long.
        """
        return self.to_bits(value).bytes

    def to_string(self, value):
        """ Convert *value* to a string.

        Note that we don't use the *str* builtin for this because some fields
        ought to have specific formatting in the output -- e.g. pointers should
        be a hex string padded to cover their width.
        """
        formats = {
            'pointer': '0x{{:0{}X}}'.format(self.bytesize*2),
            'hex': '0x{{:0{}X}}'.format(self.bytesize*2)
            }
        if 'int' in self.type:
            value += self.mod
            fstr = formats.get(self.display, '{}')
            return fstr.format(value)
        if 'float' in self.type:
            value += self.mod
            return str(value)
        if self.type in ['str', 'strz', 'bin', 'hex']:
            return value
        # If we get here something is wrong.
        msg = "Stringification of '{}' not implemented."
        raise NotImplementedError(msg, self.type)

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


