import logging
import yaml

from bitarray import bitarray

log = logging.getLogger(__name__)


class Stream:
    # Low level stream
    # Do I want to have this handle type conversions for read/write?
    def __init__(self, ba):
        self.bits = ba
        self.bytes = memoryview(self.bits)
        self.bitpos = 0

    def __len__(self):
        return len(self.bytes)

    @property
    def bytepos(self):
        if self.bitpos % 8 != 0:
            raise ValueError("Cursor is not byte-aligned")
        else:
            return self.bitpos // 8

    @bytepos.setter
    def bytepos(self, value):
        self.bitpos = value * 8

    def readbits(self, ct_bits):
        pos = self.bitpos
        end = pos + ct_bits
        out = self.bits[pos:end]
        self.bitpos = end
        return out

    def readbytes(self, ct_bytes):
        pos = self.bytepos
        end = pos + ct_bytes
        out = bytes(self.bytes[pos:end])
        self.bytepos = end
        return out

    def write(self, data):
        """ Overwrite the rom with bits or bytes

        This convenience function checks the input type and forwards to
        writebits or writebytes as appropriate. If it doesn't work as expected
        (or if it's slow), call them explicitly instead.
        """
        # can't check type(data) because it might be something odd like a
        # memoryview; can't check isinstance(sequence) because bits and bytes
        # are both sequences; can't check type of data items because data might
        # be a generator...but we can if we listify it first, so do that.
        data = list(data)
        if not data:
            # Empty input. No-op.
            return
        elif isinstance(data[0], bool):
            self.writebits(data)
        elif isinstance(data[0], int):
            self.writebytes(data)
        else:
            intype = type(data).__name__
            msg = f"Don't know how to write data from a '{intype}'"
            raise ValueError(msg)

    def writebits(self, bits, bitpos=None):
        if bitpos is not None:
            self.bitpos = bitpos
        pos = self.bitpos
        end = pos + len(bits)
        self.bits[pos:end] = bits
        self.bitpos = end

    def writebytes(self, _bytes, bytepos=None):
        if bytepos is not None:
            self.bytepos = bytepos
        pos = self.bytepos
        end = pos + len(_bytes)
        self.bytes[pos:end] = _bytes
        self.bytepos = end
