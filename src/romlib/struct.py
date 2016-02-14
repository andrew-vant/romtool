"""This module contains classes for manipulating binary structures in ROMs."""

from collections import OrderedDict
from types import SimpleNamespace

import bitstring
from bitstring import ConstBitStream, BitStream, Bits

from . import util

class StructDef(object):
    """ A definition of a type of structure.

    For example, a structure containing monster data, or weapon data. This
    class is used to read, convert, textualize, or diff structures against
    roms. The actual structures it creates are just SimpleNamespaces with a
    private attribute linking back to their definition.
    """
    def __init__(self, name, fdefs):
        """ Create a new structure type containing the fields *fdefs*."""
        self.name = name
        self.fields = OrderedDict((fdef.id, fdef) for fdef in fdefs)
        self.links = [f for f in self.fields.values() if f.pointer]
        self.data = [f for f in self.fields.values() if not f.pointer]
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
        desc = "{} field".format(name)
        for i, fdict in enumerate(fdef_dicts):
            with util.loading_context(desc, fdict['id'], i):
                display = fdict.get('display', None)
                ttable = ttables.get(display, None)
                fdef = Field.from_stringdict(fdict, ttable)
                fdefs.append(fdef)
        return StructDef(name, fdefs)

    def load(self, d):  # pylint: disable=invalid-name
        """Create a new structure from a dictionary.

        The structure's fields will be initialized from the corresponding items
        in the dictionary. They dictionary may be keyed by either the field id
        or the field label. The field id is checked first. Superfluous items
        are ignored. If the values are strings of non-string types, as when
        read from a .tsv, they will be converted.
        """
        initializers = dict()
        for field in self.fields.values():
            # Look for fields both by id and by label.
            value = d.get(field.id, d[field.label])
            if isinstance(value, str):
                value = field.load(value)
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
        bs = util.bsify(source)
        if bit_offset is not None:
            bs.pos = bit_offset
        data = dict()

        for field in self.data:
            data[field.id] = field.read(bs, bit_offset)
            bit_offset += field.bitsize

        for field in self.links:
            desc = "{} field".format(self.name)
            with util.loading_context(desc, field.id):
                pointer = self.fields[field.pointer]
                bs.pos = (data[pointer.id] + pointer.mod) * 8
                data[field.id] = field.read(bs)
                #try:
                #    bs.pos = (data[pointer.id] + pointer.mod) * 8
                #except ValueError:
                #    # Bogus pointer. FIXME: Log warning?
                #    data[field.id] = field.default
                #else:
                #    data[field.id] = field.read(bs)
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
            bs.append(field.bits(value))
        try:
            for i, byte in enumerate(bs.bytes):
                changes[offset+i] = byte
        except bitstring.InterpretError as e:
            msg = "Problem bytemapping main data of {}: {}"
            # FIXME: more appropriate exception type here.
            raise Exception(msg.format(self.name, e.msg))

        # Deal with pointers. For now pointers require whole-byte values.
        # Note that we no longer care about the struct's start point so we can
        # reuse offset.
        for field in self.links:
            value = getattr(struct, field.id)
            pointer = self.fields[field.pointer]
            offset = getattr(struct, field.pointer) + pointer.mod
            for i, byte in enumerate(field.bytes(value)):
                changes[offset+i] = byte

        # Done
        return changes

    def dump(self, struct, stringify=True, use_labels=True):
        """ Get an ordered dictionary of the structure's data.

        By default, the field labels will be used as keys if available, and all
        values will be converted to strings. The returned OrderedDict is
        suitable for sending to a tsv or similar.
        """
        return StructDef.multidump([struct], stringify, use_labels)

    @staticmethod
    def multidump(structures, stringify=True, use_labels=True):
        """ Turn a list of structures into an ordereddict for serialization.

        The odict will contain all their values and be ordered in a sane manner
        for outputting to (for example) tsv. By default, field labels will be
        used as keys if available, and values will be converted to strings.

        None of the structures may have overlapping field ids/labels.
        """

        data = []
        for i, struct in enumerate(structures):
            for field in struct._sdef.fields.values():
                key = field.label if field.label and use_labels else field.id
                value = getattr(struct, field.id)
                if stringify:
                    value = field.dump(value)
                ordering = field.sortorder(i)
                data.append((key, value, ordering))

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
        if 'str' in _type and ttable is None:
            msg = "String field {} has no text table. Check display attribute?"
            raise ValueError(msg, _id)
        self.id = _id  #pylint: disable=invalid-name
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


    @classmethod
    def from_stringdict(cls, odict, ttable=None, available_tts=None):
        """ Create a Field object from a dictionary of strings.

        This is a convenience constructor intended to be used on the input from
        tsv structure definitions. All it does is convert values to the
        appropriate types and then pass them to the regular constructor.

        Missing values are assumed to be empty strings. Extra values are
        ignored.
        """
        if ttable is None and available_tts is not None:
            ttable = available_tts.get(odict['display'], None)

        expected_fields = ['id','label','type','size','order',
                           'mod','display','comment','pointer']
        odict = {key: odict.get(key, "") for key in expected_fields}

        return Field(_id=odict['id'],
                     label=odict['label'],
                     _type=odict['type'],
                     bits=util.tobits(odict['size'], 0),
                     order=util.intify(odict['order']),
                     mod=util.intify(odict['mod']),
                     comment=odict['comment'],
                     display=odict['display'],
                     pointer=odict['pointer'],
                     ttable=ttable)

    @property
    def default(self):
        if 'str' in self.type:
            return ""
        else:
            return 0

    def read(self, source, bit_offset=None):
        """ Read a field from a bit offset within a bitstream.

        *source* may be any object that can be converted to a bitstream.

        *bit_offset* defaults to the current read position of *source* if
        possible, or to zero for objects that don't have a read position (e.g.
        bytes).

        The returned value will be a string or an int, as appropriate.
        """
        bs = util.bsify(source)
        if bit_offset is not None:
            bs.pos = bit_offset

        if 'str' in self.type:
            maxbits = self.bitsize if self.bitsize else 1024*8
            pos = bs.pos
            data = bs[pos:pos+maxbits]
            return self.ttable.decode(data.bytes)
        elif self.type == 'lbin':
            initstr = "{}:{}".format('bin', self.bitsize)
            return util.lbin_reverse(bs.read(initstr))
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
        elif self.type == 'bin':
            # Separated because you can't pass length along with bin for some
            # reason.
            return Bits(bin=value)
        elif self.type == 'lbin':
            return Bits(bin=util.lbin_reverse(value))
        else:
            init = {self.type: value, 'length': self.bitsize}
            return Bits(**init)

    def bytes(self, value):
        """ Convert a value to a bytes object.

        This may fail if the field is not a whole number of bytes long.
        """
        return self.bits(value).bytes

    def load(self, s):  # pylint: disable=invalid-name
        """ Convert the string *s* to an appropriate value type."""
        if self.type in ['str', 'strz', 'hex']:
            return s
        elif 'bin' in self.type:
            return util.undisplaybits(s, self.display)
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
        # FIXME bin types should have one letter per bit and use
        # upper/lowercase to indicate on/off. This is probably more useful
        # and keeps spreadsheets from trying to compact them to ints. Use the
        # display field to indicate the letters for each bit.
        if 'int' in self.type:
            value += self.mod
            fstr = formats.get(self.display, '{}')
            return fstr.format(value)
        if 'float' in self.type:
            value += self.mod
            return str(value)
        if 'bin' in self.type:
            return util.displaybits(value, self.display)
        if self.type in ['str', 'strz', 'hex']:
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
        typeorder = 1 if self.display == "pointer" else 0
        return nameorder, self.order, typeorder, origin_sequence_order
