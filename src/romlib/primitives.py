""" Primitive types returned when accessing struct fields

These all inherit builtin types; the difference is mainly in stringification.
"""

import logging
from math import ceil, log
from abc import ABCMeta

import bitstring

from . import util

log = logging.getLogger(__name__)


class Int(int):
    def __new__(cls, value, sz_bits=None, display=None):
        if isinstance(value, int):
            i = super().__new__(cls, value)
        else:
            i = super().__new__(cls, value, 0)

        i.display = display
        if sz_bits is None:
            sz_bits = max(i.bit_length(), 1)
        if sz_bits == 0:
            raise ValueError("Can't have a zero-bit integer")
        if sz_bits < i.bit_length():
            raise ValueError(f"{i} won't fit in {sz_bits} bits")
        i.sz_bits = sz_bits
        return i

    @property
    def hex(self):
        """ Print self as a hex representation of bytes """
        # two digits per byte; bytes are bits/8 rounding up.
        digits = ceil(self.sz_bits / 8) * 2
        sign = '-' if self < 0 else ''
        return f'{sign}0x{abs(self):0{digits}X}'

    def mod(self, modval):
        return self + modval

    def unmod(self, modval):
        return self - modval

    def __str__(self):
        if self.display:
            return getattr(self, self.display)
        else:
            return super().__str__()


class Bin(bitstring.BitArray):
    # Not sure if this should really subclass bitstring or wrap it or something
    codecs = {}

    def __new__(cls, auto=None, sz_bits=None, display=None, **kwargs):
        codec = BinCodec.get(display) if display else None
        if isinstance(auto, str) and codec:
            auto = codec.decode(auto)
        bs = super().__new__(cls, auto, **kwargs)
        bs.codec = codec
        return bs

    def mod(self, mod_s):
        if mod_s == 'lsb0':
            return type(self)(util.lbin_reverse(self))
        else:
            return self

    def unmod(self, mod_s):
        return self.mod(mod_s)

    def __str__(self):
        if self.codec is None:
            return '0b' + self.bin
        else:
            return self.codec.encode(self)


class BinCodec:
    """ encode/decode strings and bools based on a format str """
    registry = {}

    @classmethod
    def get(cls, keystr):
        if keystr not in cls.registry:
            cls.registry[keystr] = cls(keystr)
        return cls.registry[keystr]

    class InputLengthError(ValueError):
        def __init__(self, keystr, _input):
            assert len(keystr) != len(_input)
            self.keystr = keystr
            self.input = _input
            msg = (f"length of key '{keystr}' ({len(keystr)}) doesn't "
                   f"match length of input '{_input}' ({len(_input)}) ")
            super().__init__(msg)

    def __init__(self, keystr):
        self.keystr = keystr
        if len(set(keystr)) < len(keystr):
            log.warn("display string '%s' has repeated characters", keystr)

        # start with a list of tuples, where each item is the 'falsy char' and
        # 'truthy char' for that position in a string. Use that to build
        # encoding and decoding map sets.
        self.key = [('0', '1')
                    if char == '?'
                    else (char.lower(), char.upper())
                    for char in keystr]

        for i, (truthy, falsy) in enumerate(self.key):
            if truthy == falsy:
                msg = f'invalid display string char: {util.bracket(keystr, i)}'
                raise ValueError(msg)

        self.encoding_map = [{True: ch_true, False: ch_false}
                             for ch_false, ch_true in self.key]
        self.decoding_map = [{ch_true: True, ch_false: False}
                             for ch_false, ch_true in self.key]

    def encode(self, bools, strict=True):
        if len(bools) != len(self.keystr) and strict:
            raise self.InputLengthError(self.keystr, bools)

        return ''.join(char[bit] for char, bit
                       in zip(self.encoding_map, bools))

    def decode(self, text, strict=True):
        if len(text) != len(self.keystr) and strict:
            raise self.InputLengthError(self.keystr, text)

        return [dmap[char] for dmap, char
                in zip(self.decoding_map, text)]


class Primitive:
    """ A struct-like class for primitives """
    def __init__(self, bstype, sz_bits, display=None):
        self.bstype = bstype
        self.sz_bits = sz_bits
        self.display = display
        self.type = getcls(bstype)
        self.bsfmt = f'{bstype}:{sz_bits}'

    def __call__(self, stream, offset):
        return self.read(stream, offset)

    def read(self, stream, offset):
        stream.pos = offset
        bits = stream.read(self.bsfmt)
        return self.type(bits, self.sz_bits, self.display)

    def write(self, stream, offset, value):
        stream.pos = offset
        stream.overwrite(f'{self.bsfmt}={value}')


def getbst(type_string):
    """ Get bitstring type for a given type string """
    bstype = {'str': 'bytes'}
    return bstype.get(type_string, type_string)


def getcls(type_string):
    """ Get the right class for a given type string """
    strtypes = {'int': Int,
                'str': str,
                'bin': Bin,}
    for substr, cls in strtypes.items():
        if substr in type_string:
            return cls
    raise KeyError("Invalid type string")
