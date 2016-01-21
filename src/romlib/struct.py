"""This module contains classes for manipulating binary structures in ROMs."""

from collections import OrderedDict
from types import SimpleNamespace

from bitstring import *

from . import util


class StructDef(object):
    def __init__(self, name, fdefs):
        """ Create a new structure type containing the fields *fdefs*."""
        # FIXME: raise an exception for a structure for which the main data
        # members don't sum to a whole-byte size?
        if texttables is None:
            texttables = {}

        self.fields = OrderedDict((fdef.id, fdef) for fdef in fdefs)
        self.links = [f for f in fields.values() if f.pointer]
        self.data =  [f for f in fields.values() if not f.pointer]
        self.cls = type(name, (SimpleNamespace,), {"_sdef": self})

    @classmethod
    def from_stringdicts(cls, name, fdef_dicts, ttables=None):
        """ Create a new structure from a list of dictionaries.

        The dictionaries must be valid input to Field.from_stringdict.
        *ttables* should be a dictionary of text tables to use for decoding
        string fields. String fields will be mapped to text tables by the
        'display' key.
        """
        if ttables is None:
            ttables = {}
        fdefs = []
        for d in fdef_dicts:
            display = d.get('display', None)
            ttable = ttables.get(display, None)
            fdef = Field.from_stringdict(d, ttable)
            fdefs.append(fdef)
        return StructDef(name, fdefs)

    @classmethod
    def from_primitive(cls, _id, _type, bits,
                       label=None, mod=0, display=None, ttable=None):
        field = Field(_id=_id,
                      _type=_type,
                      label=label,
                      bits=bits,
                      mod=mod,
                      display=display,
                      ttable=ttable)
        return StructDef(_id, [field])

    def load(self, d):  # pylint: disable=invalid-name
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

    def read(self, source, bit_offset=None):
        """ Read in a new structure

        source -- The data source to read from. This may be a bitstring or any
                  object that can be converted to one, e.g a file object.

        bit_offset -- The offset to start reading from.

        If the offset is not provided, it will try to use the read position of
        *source* by looking for f.tell() (on file objects) or bs.pos (for
        bitstrings). Otherwise it will default to zero.

        If *source* is a file object, it must be opened in binary mode.
        """
        if bit_offset is None:
            bit_offset = util.bit_offset(source)
        bs = ConstBitStream(source)
        bs.pos = bit_offset

        data = {field.id: field.read(bs)
                for field in self.data}

        for field in self.links:
            pointer = self.fields[field.pointer]
            bs.pos = (data[pointer.id] + pointer.mod) * 8
            data[field.id] = field.read(bs)
        return self.cls(**data)

    def bytemap(self, struct, offset=0):
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

    def dump(self, struct, stringify=True, use_labels=True):
        """ Get an ordered dictionary of the structure's data.

        By default, the field labels will be used as keys if available, and all
        values will be converted to strings. The returned OrderedDict is
        suitable for sending to a csv or similar.
        """
        return StructDef.to_mergedict([struct], stringify, use_labels)

    @staticmethod
    def multidump(structures, stringify=True, use_labels=True):
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
                ordering = field.sortorder(i)
                data.append(key, value, ordering)

        data.sort(key=lambda d: d[-1])
        return OrderedDict(d[:2] for d in data)


class Field(object):  # pylint: disable=too-many-instance-attributes
    """ An individual field of a structure.

    For example, a 3-byte integer or a delimiter-terminated string. Most of the
    methods of Field are intended to transport value types to and from strings,
    bitstreams, file objects, etc.
    """
    def __init__(self, _id, label, _type, bits,
                 order=0, mod=0, comment="",
                 display=None, pointer=None, ttable=None):
        self.id = _id
        self.label = label
        self.type = _type
        self.bitsize = bits
        self.bytesize = util.divup(bits, 8)
        self.order = order
        self.mod = mod
        self.comment = comment
        self.display = display
        self.pointer = pointer
        self.ttable = ttable

        # FIXME: should probably raise an exception if someone asks for a
        # string type without a text table.

    def from_stringdict(cls, odict, ttable=None, available_tts=None):
        if ttable is None and available_tts is not None:
            ttable = available_tts.get(odict['display'], None)
        return Field(_id=odict['id'],
                     label=odict['label'],
                     _type=odict['type'],
                     bitsize=util.tobits(odict['size']),
                     order=int(odict['order']) if odict['order'] else 0,
                     mod=int(odict['mod']) if odict['mod'] else 0,
                     comment=odict['comment'],
                     display=odict['display'],
                     pointer=odict['pointer'],
                     ttable=ttable)

    def read(self, source, bit_offset=None):
        """ Read a field from a bit offset within a bitstream.

        *source* may be any object that can be converted to a bitstream.

        *bit_offset* defaults to the current read position of *source* if
        possible, or to zero for objects that don't have a read position (e.g.
        bytes).

        The returned value will be a string or an int, as appropriate.
        """
        if bit_offset is None:
            bit_offset = util.bit_offset(source)
        bs = ConstBitStream(source)
        bs.pos = bit_offset

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

    def bits(self, value):
        """ Convert a value to a Bits object."""
        if 'str' in self.type:
            return Bits(self.ttable.encode(value))
        else:
            init = {self.type: value, 'length': self.bitsize}
            return Bits(**init)

    def bytes(self, value):
        """ Convert a value to a bytes object.

        This may fail if the field is not a whole number of bytes long.
        """
        return self.to_bits(value).bytes

    def load(self, s):  # pylint: disable=invalid-name
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

    def dump(self, value):
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

    def sortorder(self, origin_sequence_order=0):
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
