import codecs
import abc
from itertools import product, chain

import bitstring

from . import util.


class MetaField(abc.ABCMeta):
    required_attrs = ['id', 'label', 'type', 'size', 'order', 'mod',
                      'display', 'pointer', 'comment']
    nonone_attrs = ['id','type','size']

    def __init__(cls, name, bases, dct):
        for field in required_fields:
            if dct[field] is None:
                msg = "Class %s doesn't define required attribute %s"
                raise ValueError(msg, cvar)
        super().__init__(cls, name, bases, dct)


class Field(object, metaclass=MetaField):
    # Default values
    id = None
    label = None
    type = None
    size = None
    order = 0
    mod = None
    display = None
    pointer = None
    comment = ""

    def __init__(self, parent, value=None, bs=None, string=None):
        self.data = BitArray(self.size)
        self.parent = parent
        if value is not None:
            self.value = value
        elif bs is not None:
            self.bits = bs
        elif string is not None:
            self.string = string

    @classmethod
    @property
    def bytesize(cls):
        if self.size is None:
            return None
        else:
            return util.divup(cls.size, 8)

    @property
    def bits(self):
        return Bits(self.data)

    @bits.setter
    def bits(self, bs):
        if self.size is not None and len(bs) != self.size:
            msg = "Input size %s != field size %s"
            raise ValueError(msg, len(bs), self.size)
        self.data = BitArray(bs)

    @abstractmethod
    @property
    def value(self):
        raise NotImplementedError

    @abstractmethod
    @value.setter
    def value(self, value):
        raise NotImplementedError


    @abstractmethod
    @property
    def string(self):
        raise NotImplementedError

    @abstractmethod
    @str.setter
    def string(self, s):
        raise NotImplementedError


class NumField(Field):
    size = 8
    mod = 0
    display = ""

    @property
    def value(self):
        return getattr(self.data, self.type) + mod

    @value.setter
    def value(self, value):
        self.data.overwrite(Bits(**{self.type: value - mod}))

    @property
    def string(self):
        fstr = util.int_format_str(self.display, self.size)
        return fstr.format(self.value)

    @str.setter
    def string(self, s):
        self.value = int(s, 0)


class StringField(Field):
    display = "ascii"

    @property
    def string(self):
        return codecs.decode(self.data.bytes, self.display)

    @string.setter
    def string(self, value):
        data = codecs.encode(value, self.display)
        if self.size is not None:
            bytesize = self.size // 8
            if len(data) > bytesize
                msg = "String '%s' (%s bytes) too long for field '%s' (%s bytes)"
                raise ValueError(msg, value, len(data), self.name, bytesize)
            if len(data) < bytesize:
                # Pad short strings with spaces
                padbyte = codecs.encode(" ", self.display)
                padding = [padbyte] * (bytesize - len(data))
                data += bytes(padding)
        bs = BitArray(bytes=data)
        assert size is not None or len(bs) == self.size
        self.data = bs

    @property
    def value(self):
        return self.string

    @value.setter
    def value(self, value):
        self.string = value


class BinField(Field):
    mod = "msb0"

    @property
    def string(self):
        return util.displaybits(self.value, self.display)

    @string.setter
    def string(self, s):
        self.value = Bits(bin=util.undisplaybits(s, self.display))

    @property
    def value(self):
        bs = self.bits
        if self.mod == "msb0":
            return self.bits
        elif self.mod == "lsb0":
            return util.lbin_reverse(self.bits)
        else:
            msg = "Bit ordering '%s' is not a thing"
            raise NotImplementedError(msg, self.mod)

    @value.setter
    def value(self, value):
        if self.mod == "msb0":
            self.bits = value
        elif self.mod == "lsb0":
            self.bits = util.lbin_reverse(value)
        else:
            msg = "Bit ordering '%s' is not a thing"
            raise NotImplementedError(msg, self.mod)


def define_field(name, spec):
    spec = fixspec(spec.copy())
    base = basecls(spec['type'])
    cls = type(name, (base,), spec)
    return cls


def basecls(tp):
    if "int" in tp or "float" in tp:
        return NumField
    elif "bin" in tp:
        return BinField
    elif "str" in tp:
        return StringField
    else:
        return Field


def fixspec(spec):
    """ Unstringify any properties from spec that need it"""
    unstring = {
            'size': lambda s: util.tobits(s, 0),
            'order': lambda s: util.intify(s),
            'mod': lambda s: util.intify(s)
            }

    # empty strings get stripped out; the parent provides defaults.
    for k, v in spec.items():
        if v == "":
            del(spec[k])

    # Uncast string values get cast
    for key, func in unstring.items():
        if isinstance(spec[key], str):
            spec[key] = unstring[func](spec[key])
