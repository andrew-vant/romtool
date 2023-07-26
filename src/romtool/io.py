import logging
import enum
import hashlib
import zlib
import codecs

from bitarray import bitarray
from bitarray.util import int2ba, ba2int, bits2bytes, ba2hex, hex2ba
from anytree import NodeMixin
from anytree.search import find
from collections import namedtuple
from collections.abc import Hashable
from functools import partial
from io import BytesIO

from .util import bytes2ba, HexInt, cache, chunk

log = logging.getLogger(__name__)
trace = partial(log.log, logging.NOTSET)


class Unit(enum.IntEnum):
    bits = 1
    bytes = 8
    kb = 8 * 2**10
    mb = 8 * 2**20
    gb = 8 * 2**30

    def __contains__(self, item):
        return item in type(self).__members__

    def __str__(self):
        return str(self.name)

class BitArrayView(NodeMixin):
    """ Low level data handler

    A BitArrayView is a view on part of a bitarray -- typically a data block (header
    vs rom), or a structure's contents. Slicing a view will produce a smaller
    view. The "step" slice attribute has been altered; it represents the
    size-unit of the slice indexes.

    Hence, view[1:8:Unit.bytes] would return a view containing bytes one
    through seven inclusive. view[1:8:Unit.bits] would get a view of
    *bits* one through seven inclusive.

    Slices are indexed relative to the view's start and end, not the
    underlying bitarray. The underlying bitarray is available as BitArrayView.bits.
    """
    def __new__(cls, auto, *args, **kwargs):
        # bitarrays are unhashable. Farm to separate new for view vs bitarray
        # and just cache the view one.
        return (cls._newcache(auto, *args, **kwargs)
                if isinstance(auto, Hashable)
                else super().__new__(cls))

    @classmethod
    @cache
    def _newcache(cls, auto, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, auto, offset=None, length=None, name=None):
        self._ba = None
        if isinstance(auto, BitArrayView):
            self.parent = auto
        elif isinstance(auto, bitarray):
            self.parent = None
            self._ba = auto
        else:
            raise TypeError(f"Don't know what to do with a {type(auto)}")

        self.name = name
        self.offset = offset or 0
        self.abs_start = self.offset + (0 if not self.parent else self.parent.abs_start)
        self.length = (length if length
                       else (len(self.parent) - self.offset) if self.parent
                       else len(self.ba) - self.abs_start)
        if self.length < 0:
            raise ValueError("View runs off the end of the underlying bitarray")
        self.abs_end = self.abs_start + len(self)
        self.abs_slice = slice(self.abs_start, self.abs_end)
        assert len(self.bits) == len(self), f"{len(self.bits)} != {len(self)}"

    def __len__(self):
        return self.length

    def __hash__(self):
        return hash((id(self.parent), self.offset, self.length, self.name))

    def __eq__(self, other):
        return hash(self) == hash(other)

    @property
    def sha1(self):
        """ Get sha1 hash of contents """
        return hashlib.sha1(self.bytes).hexdigest()

    @property
    def md5(self):
        return hashlib.md5(self.bytes).hexdigest()

    @property
    def crc32(self):
        checksum = zlib.crc32(self.bytes)
        return f"{checksum:08X}"

    @property
    def ct_bytes(self):
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        else:
            return len(self) // Unit.bytes

    @property
    def ct_bits(self):
        return len(self)

    @property
    def os_bytes(self):
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        else:
            return self.offset // Unit.bytes

    @property
    def os_bytemod(self):
        os_bytes, rm_bits = divmod(self.offset, Unit.bytes)
        os_bytes = HexInt(os_bytes, len(self.root).bit_length())
        return os_bytes, rm_bits

    def __str__(self):
        bits = ''.join('1' if b else '0' for b in self[:16])
        excess = max([len(self) - len(bits), 0])
        if len(bits) < len(self):
            excess = len(self) - len(bits)
            bits += f'...({excess} more)'
        return f'BitArrayView({bits})'

    def __repr__(self):
        _inobj = 'parent' if self.parent else 'ba'
        return f'BitArrayView({_inobj}, {self.offset}, {len(self)})'

    def origin(self, name):
        return find(self.root, lambda n: n.name == name)

    @property
    def end(self):
        return self.offset + len(self)

    def __getitem__(self, sl):
        if not isinstance(sl, slice):
            return self.bits[sl]

        start, stop, unit = sl.start, sl.stop, sl.step

        if unit is None:
            unit = 1
        if isinstance(unit, str):
            unit = Unit[unit]

        if start is None:
            start = 0
        else:
            start *= unit

        if stop is None:
            stop = self.end
        else:
            stop *= unit

        if start < 0:
            start += len(self)
        if stop < 0:
            stop += len(self)

        if self.offset + stop > len(self.ba):
            raise IndexError("slice took a long walk off a short pier")
        if self.offset + start < 0:
            raise IndexError("slice took a short walk off a long pier")

        return BitArrayView(self, start, stop-start)

    @property
    def ba(self):
        return self._ba or self.root.ba

    #
    # TYPE INTERPRETATION PROPERTIES START HERE
    #

    @property
    def hex(self):
        return ba2hex(self.bits)

    @hex.setter
    def hex(self, s):
        self.bits = hex2ba(s, endian=self.ba.endian())

    @property
    def bits(self):
        bits = self.ba[self.abs_slice]
        return bits

    @bits.setter
    def bits(self, ba):
        old = self.bits
        if len(ba) != len(self):
            msg = f"expected {len(self)} bits, got {len(ba)}"
            raise ValueError(msg)
        self.ba[self.abs_slice] = ba
        new = self.bits
        if new != old:
            trace("change detected: %s -> %s", old, new)

    @property
    def bin(self):
        return ''.join('1' if bit else '0' for bit in self)

    @bin.setter
    def bin(self, string):
        self.bits = bitarray(string, endian=self.ba.endian())

    @property
    def bytes(self):
        return self.bits.tobytes()

    @bytes.setter
    def bytes(self, _bytes):
        self.bits = bytes2ba(_bytes, endian=self.ba.endian())

    @property
    def uint(self):
        return ba2int(self.bits)

    @uint.setter
    def uint(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        old = self.uint
        self.bits = int2ba(i, length=len(self), endian=self.ba.endian())
        if old != self.uint:
            trace("change detected: %s -> %s", old, self.uint)

    @property
    def uintbe(self):
        return self.uint

    @uintbe.setter
    def uintbe(self, i):
        self.uint = i

    @property
    def uintle(self):
        return int.from_bytes(self.bytes, 'little')

    @uintle.setter
    def uintle(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        self.bytes = (i).to_bytes(bits2bytes(len(self)), 'little')

    @property
    def int(self):
        return ba2int(self.bits, signed=True)

    @int.setter
    def int(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        old = self.int
        self.bits = int2ba(
                i,
                length=len(self),
                endian=self.ba.endian(),
                signed=True
                )
        if old != self.int:
            trace("change detected: %s -> %s", old, self.int)

    @property
    def nbcdle(self):
        """ Natural binary-coded decimal integers, little-endian """
        return sum(10 ** n * nybble.uint
                   for n, nybble
                   in enumerate(chunk(self, 4)))

    @nbcdle.setter
    def nbcdle(self, i):
        for nybble in chunk(self, 4):
            i, digit = divmod(i, 10)
            nybble.uint = digit

    @property
    def nbcdbe(self):
        """ Natural binary-coded decimal integers, big-endian """
        raise NotImplementedError

    @nbcdbe.setter
    def nbcdbe(self, i):
        raise NotImplementedError
