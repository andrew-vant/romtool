""" Primitive types returned when accessing struct fields

These all inherit builtin types; the difference is mainly in stringification.
"""

import logging
import string
from math import ceil, log
from abc import ABCMeta

import bitstring

from . import util

log = logging.getLogger(__name__)
builtins = {}

class Primitive(ABC):
    # Default __new__ given mainly to provide the expected arguments
    def __new__(cls, value, sz_bits, fmt):
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def load(cls, string, sz_bits, fmt):
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def read(cls, stream, sz_bits, mod, fmt):
        raise NotImplementedError

    @abstractmethod
    def write(self, stream, sz_bits, mod):
        raise NotImplementedError

    @abstractmethod
    def dump(self):
        raise NotImplementedError

    def __str__(self):
        return self.dump()

    def __repr__(self):
        name = type(self).__name__
        return f'{name}({self}, {self.sz_bits}, {self.fmt})'


class BaseInt(Primitive, int):
    # This gets overridden in subclasses and is used to determine the type to
    # pass to bitstring.read
    _bstype = None

    def __new__(cls, value, sz_bits=None, fmt=None):
        i = int.__new__(cls, value)
        i.sz_bits = sz_bits or value.sz_bits
        i.fmt = fmt

        if i.sz_bits is None:
            raise ValueError('No size given')
        elif i.sz_bits == 0:
            raise ValueError("Can't have a zero-size int")
        elif i.sz_bits < i.bit_length():
            raise ValueError(f"{i} won't fit in {i.sz_bits} bits")
        return i

    @classmethod
    def read(cls, stream, sz_bits, mod, fmt):
        value = stream.read(f'{cls._bstype}:{sz_bits}')
        value += mod
        if fmt == 'hex':
            value = HexInt(value)
        return value

    @classmethod
    def load(cls, string, sz_bits, fmt):
        return cls(int(string, 0), sz_bits, fmt)

    @property
    def hex(self):
        """ Print self as a hex representation of bytes """
        # two digits per byte; bytes are bits/8 rounding up.
        digits = ceil(self.sz_bits / 8) * 2
        sign = '-' if self < 0 else ''
        return f'{sign}0x{abs(self):0{digits}X}'

    def dump(self):
        if self.fmt == 'hex':
            return self.hex
        elif self.fmt:
            return self.fmt.format(self)
        else:
            return int.__str__(self)

    def write(self, stream, value, sz_bits, mod):
        # Helper method for subclasses that only differ by bstype
        value -= mod
        stream.overwrite(f'{bstype}:{sz_bits}={value}')

    @staticmethod
    def _builtins():
        bases = (BaseInt,)
        bstypes = ['uintle', 'uintbe', 'uint',
                   'intle', 'intbe']
        return {bstype: type(key, bases, {'_bstype': bstype})
                for bstype in bstypes}


class Flag(Primitive, BaseInt):
    _bstype = 'uint'
    valid_letters = list(string.ascii_letters)

    def __new__(cls, value, sz_bits, fmt):
        f = BaseInt.__new__(cls, value, sz_bits, fmt)
        if f.sz_bits != 1:
            raise ValueError("flags must be exactly one bit in size")
        if f.fmt and f.fmt not in cls.valid_letters:
            raise ValueError("flag display format must be a single letter")
        return f

    @classmethod
    def load(cls, string, sz_bits, fmt):
        if string == fmt.upper():
            value = True
        elif string == fmt.lower():
            value = False
        else:
            value = strtobool(string)
        return cls(value, sz_bits, fmt)

    def char(self):
        # used by structs to get a single-char representation
        if not self.fmt:
            return '1' if self else '0'
        else:
            return self.fmt.upper() if self else self.fmt.lower()


class String(Primitive, str):
    def __new__(cls, string, sz_bits, fmt):
        s = str.__new__(string)
        s.sz_bits = sz_bits
        s.fmt = fmt
        return s

    @classmethod
    def load(cls, string, sz_bits, fmt):
        return cls(string, sz_bits, fmt)

    @classmethod
    def read(cls, stream, sz_bits, mod, fmt):
        return stream.read(sz_bits).bytes.decode(fmt)

    def write(self, stream, sz_bits, mod):
        # Only write if the text has changed. This avoids spurious patches when
        # there is more than one valid encoding for text.
        pos = stream.pos
        old = self.read(stream, sz_bits, mod, self.fmt)
        if self != old:
            stream.pos = pos
            stream.overwrite(self.encode(self.fmt))

    def dump(self):
        return self


def init():
    builtins.update(BaseInt._builtins())
    builtins['str'] = String
    builtins['flag'] = Flag
