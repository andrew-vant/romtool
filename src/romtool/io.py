""" Low-level manipulation of ROM data.

The BitArrayView class makes up most of this module. Its attributes provide
I/O translation between primitive types and the underlying bitarray.
"""
import logging
import enum
import hashlib
import zlib
from collections.abc import Hashable
from functools import cache, partial

from bitarray import bitarray
from bitarray.util import int2ba, ba2int, bits2bytes, ba2hex, hex2ba

from .util import FormatSpecifier, HexInt, NodeMixin
from .util import bytes2ba, chunk, throw

log = logging.getLogger(__name__)
trace = partial(log.log, logging.NOTSET)


class Unit(enum.IntEnum):
    """ Lengths of common size units in bits. """
    # pylint: disable=invalid-name
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

    A BitArrayView is a view on part of a bitarray -- typically a data block
    (header vs rom), or a structure's contents. Slicing a view will produce a
    smaller view. The "step" slice attribute has been altered; it represents
    the size-unit of the slice indexes.

    Hence, view[1:8:Unit.bytes] would return a view containing bytes one
    through seven inclusive. view[1:8:Unit.bits] would get a view of
    *bits* one through seven inclusive.

    Slices are indexed relative to the view's start and end, not the
    underlying bitarray. The underlying bitarray is available as
    BitArrayView.bits.
    """
    def __new__(cls, auto, *args, **kwargs):
        # Instantiating a view is surprisingly expensive, and views have no
        # mutable state, so cache them and return an existing one if
        # possible. The additional check for bitarray here is a workaround
        # for bitarray issue #232.
        return (cls._newcache(auto, *args, **kwargs)
                if isinstance(auto, Hashable)
                and not isinstance(auto, bitarray)
                else super().__new__(cls))

    @classmethod
    @cache
    def _newcache(cls, auto, *args, **kwargs):  # pylint: disable=unused-argument
        # unused-argument is disabled because we only need the arguments
        # for caching purposes. object.__new__ only expects one argument.
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
        self.abs_start = (self.offset if not self.parent
                          else self.parent.abs_start + self.offset)
        self.length = (length if length
                       else (len(self.parent) - self.offset) if self.parent
                       else len(self.ba) - self.abs_start)
        if self.length < 0:
            raise ValueError("View runs off the end of the data")
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
    def _endian(self):
        """ Compatibility shim for bitarray.endian()

        bitarray v3.4.0 replaced the endian() method with a data descriptor.
        This forwards to whatever's appropriate. Remove it once 3.4+
        propagates to current distro versions; for now I want to allow for
        using the distro-provided package.
        """
        return (self.ba.endian
                if isinstance(self.ba.endian, str)
                else self.ba.endian())

    @property
    def sha1(self):
        """ SHA1 hash of the view's contents. """
        return hashlib.sha1(self.bytes).hexdigest()

    @property
    def md5(self):
        """ MD5 hash of the view's contents. """
        return hashlib.md5(self.bytes).hexdigest()

    @property
    def crc32(self):
        """ CRC32 checksum of the view's contents. """
        checksum = zlib.crc32(self.bytes)
        return f"{checksum:08X}"

    @property
    def ct_bytes(self):
        """ Number of bytes in the view.

        Raises ValueError if the view is not an integer number of bytes long.
        """
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        return len(self) // Unit.bytes

    @property
    def ct_bits(self):
        """ Number of bits in the view. """
        return len(self)

    @property
    def os_bytes(self):
        """ Offset of the view in bytes.

        Raises ValueError if the offset is not an integer number of bytes.
        """
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        return HexInt(self.offset // Unit.bytes)

    @property
    def os_bytemod(self):
        """ Offset in bytes rounded down, and remainder in bits. """
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

    def __format__(self, format_spec):
        spec = FormatSpecifier.parse(format_spec)
        if spec.type and spec.type in 'Xx':
            return format(self.uintbe, format_spec)
        log.error("spec problem: %s | %r | %r", format_spec, spec, spec.type)
        return super().__format__(format_spec)

    def __repr__(self):
        _inobj = 'parent' if self.parent else 'ba'
        return f'BitArrayView({_inobj}, {self.offset}, {len(self)})'

    @property
    def end(self):
        """ The end of this view relative to its parent. """
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
            stop = self.end - self.offset
        else:
            stop *= unit

        if start < 0:
            start += len(self)
        if stop < 0:
            stop += len(self)

        if (self.offset + stop > len(self.ba)) or (self.offset + start < 0):
            raise IndexError(
                f"bad slice: "
                f"{sl.start}:{sl.stop}:{unit} -> {start}:{stop}:{unit} "
                f"(our length: {len(self)}@{self.offset}"
                )
        return BitArrayView(self, start, stop-start)

    @property
    def ba(self):
        """ Get the view's underlying bitarray. """
        return self._ba or self.root.ba

    #
    # TYPE INTERPRETATION PROPERTIES START HERE
    #

    @property
    def hex(self):
        """ Get or set view contents as a hex string. """
        return ba2hex(self.bits)

    @hex.setter
    def hex(self, s):
        self.bits = hex2ba(s, endian=self._endian)

    @property
    def bits(self):
        """ Get or set view contents as a bitarray. """
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
        """ Get or set view contents as a string of 1s and 0s. """
        return ''.join('1' if bit else '0' for bit in self)

    @bin.setter
    def bin(self, string):
        self.bits = bitarray(string, endian=self._endian)

    @property
    def bytes(self):
        """ Get or set view contents as a byte sequence. """
        return self.bits.tobytes()

    def write(self, _bytes):
        """ Write bytes to the start of the view.

        Bytes after those written are left unchanged.
        """
        # FIXME: fail if writing off the end of the view?
        self[:len(_bytes):Unit.bytes].bytes = _bytes

    @bytes.setter
    def bytes(self, _bytes):
        self.bits = bytes2ba(_bytes, endian=self._endian)

    @property
    def uint(self):
        """ Get or set view contents as an unsigned integer. """
        return ba2int(self.bits)

    @uint.setter
    def uint(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        old = self.uint
        self.bits = int2ba(i, length=len(self), endian=self._endian)
        if old != self.uint:
            trace("change detected: %s -> %s", old, self.uint)

    @property
    def uintbe(self):
        """ Get or set view contents as a big-endian unsigned integer. """
        return int.from_bytes(self.bytes, 'big')

    @uintbe.setter
    def uintbe(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        self.bytes = (i).to_bytes(bits2bytes(len(self)), 'big')

    @property
    def uintle(self):
        """ Get or set view contents as a little-endian unsigned integer. """
        return int.from_bytes(self.bytes, 'little')

    @uintle.setter
    def uintle(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        self.bytes = (i).to_bytes(bits2bytes(len(self)), 'little')

    @property
    def int(self):
        """ Interpret view contents as a signed integer. """
        return ba2int(self.bits, signed=True)

    @int.setter
    def int(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        old = self.int
        self.bits = int2ba(
                i,
                length=len(self),
                endian=self._endian,
                signed=True
                )
        if old != self.int:
            trace("change detected: %s -> %s", old, self.int)

    @property
    def nbcdle(self):
        """ Natural binary-coded decimal integers, little-endian """
        return sum(10 ** n * nybble.uint
                   if nybble.uint < 10
                   else throw(ValueError, f'invalid nbcd encoding: 0x{self:X}')
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
        raise NotImplementedError("nbcdbe encoding not implemented yet")

    @nbcdbe.setter
    def nbcdbe(self, i):
        raise NotImplementedError("nbcdbe encoding not implemented yet")

    @property
    def nbcd(self):
        """ Natural binary-coded decimal integers, <1 byte """
        if len(self) > Unit.bytes:
            raise ValueError("nbcd values of >1 byte must specify endianness")
        return self.nbcdle

    @nbcd.setter
    def nbcd(self, i):
        if len(self) > Unit.bytes:
            raise ValueError("nbcd values of >1 byte must specify endianness")
        self.nbcdle = i
