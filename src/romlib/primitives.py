""" Primitive types returned when accessing struct fields

These all inherit builtin types; the difference is mainly in stringification.
"""

import logging
from math import ceil, log

import bitstring

from . import util

log = logging.getLogger(__name__)


class UInt(int):
    def __new__(cls, value, sz_bits=None, display=None, *args, **kwargs):
        i = super().__new__(cls, value, *args, **kwargs)
        if sz_bits is None:
            sz_bits = max(i.bit_length(), 1)

        # sanity checks
        if i < 0:
            raise ValueError("uints must be >= 0")
        if i.bit_length() > sz_bits or sz_bits <= 0:
            raise ValueError(f"{value} can't fit in {sz_bits} bits")

        i.sz_bits = sz_bits
        i.display = display
        return i

    @property
    def hex(self):
        """ Print self as a hex representation of bytes """
        # two digits per byte; bytes are bits/8 rounding up.
        digits = ceil(self.sz_bits / 8) * 2
        return f'0x{self:0{digits}X}'

    def __str__(self):
        if self.display:
            return getattr(self, self.display)
        else:
            return super().__str__()


class Bin(bitstring.Bits):
    enc_prefix = 'fmt:'

    def __new__(cls, auto=None, codec=None, *args, enc=None, **kwargs):
        """ Adds a fmt: prefix to the bitstring auto initializer """
        if isinstance(auto, str) and auto.startswith(cls.enc_prefix):
            enc = auto[len(cls.enc_prefix):]
            auto = None
        if enc:
            auto = codec.decode(enc)
        return super().__new__(cls, auto, *args, **kwargs)

    def __init__(self, auto=None, codec=None, *args, **kwargs):
        # For some reason we can't do this in __new__, probably because the
        # superclass is immutable.
        self.codec = codec

    def __str__(self):
        if self.codec is None:
            return super().__str__()
        return self.codec.encode(self)

class BinCodec:
    """ encoding/decode strings and bools based on a format str """
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
