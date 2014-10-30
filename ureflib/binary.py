import logging
import math
import specs

class BinaryException(Exception):
    pass

class BinaryRangeException(BinaryException):
    pass

class BinaryFormatError(BinaryException):
    pass

def read(f, spec, offset = 0):
    """ Read an arbitrary object from a ROM.

    The offset is the location in the file that the spec considers
    "zero." For example, if you're reading a table entry, the passed
    offset should be the beginning of that entry.
    """

    # Figure out where to start and how much to read.
    obytes, obits = decompose_bytecount(spec['offset'])
    wbytes, wbits = decompose_bytecount(spec['width'])

    if wbytes > 0 and wbits > 0:
        raise ValueError("Fractional byte widths > 0 not supported.")

    f.seek(offset + obytes)
    data = f.read(wbytes + int(math.ceil(wbits / 8)))

    # Call table for the simpler type possibilities:
    unpackers = {
        "int.be": lambda data: int.from_bytes(data, byteorder="big"),
        "int.le": lambda data: int.from_bytes(data, byteorder="little"),
        "ti.be": lambda data: unpack_tinyint(data[0], obits, wbits, "big"),
        "ti.le": lambda data: unpack_tinyint(data[0], obits, wbits, "little"),
        "flag": lambda data: unpack_flag(data[0], obits),
        "bitfield": lambda data: unpack_bitfield(data[0], obits, wbits)
    }

    return unpackers[spec['type']](data)


def decompose_bytecount(s):
    """ Turn a bytecount string into its bytes and bits parts.

    The string should be in the format x.y, where x is the number of
    bytes and y is any additional bits. Less than one byte should be
    written as 0.y. Integer bytes may omit the decimal and bits.
    """

    parts = s.split(".")
    if len(parts) > 2:
        raise BinaryFormatError("'{}' is not a valid bytecount.")

    bytes = int(parts[0], 0)
    bits = int(parts[1], 0) if len(parts) > 1 else 0
    return bytes, bits

def unpack_tinyint(byte, offset = 0, width = 8, bitorder="big"):
    """ Unpack an integer that is smaller than one byte.

    The width and offset must be specified in bits, and default to the whole
    byte. Offset is from the left end regardless of the order of the
    bits. I'm not sure if anything, anywhere uses a little endian tinyint, but
    it is supported.
    """

    # Sanity checks.
    if byte > 255:
        raise ValueError(
            "Tried to unpack a tinyint that isn't tiny. Value: {}", byte)
    if offset < 0:
        raise IndexError("Tried to unpack a tinyint from a negative offset.")
    if offset + width > 8:
        raise IndexError("Tried to unpack a tinyint from past the end of the byte.")
    if width < 1:
        raise ValueError("Tried to unpack a tinyint of width {}.", width)
    if bitorder not in ["big","little"]:
        raise ValueError("'{}' is not a bit ordering.", bitorder)


    # Figure out which bits are set.
    bitlist = [byte & 0b10000000 >> i for i in range(8)]

    # Slice out the bits we're interested in.
    bits = bitlist[offset:offset+width]

    # The calculation for summing the bits is simpler starting from the right,
    # so if the bits are big-endian (which they probably are), reverse them.
    if bitorder == "big":
        bits.reverse()

    # Do the math.
    return sum(2**i for i in range(width) if bits[i])

def unpack_flag(byte, offset):
    """ Extract a one-bit flag from a byte. Returns a bool. """
    return byte & 0b10000000 >> offset != 0

def unpack_bitfield(byte, offset = 0, width = 8):
    """ Return a string representing a bitfield.

    Offset and width are expressed in bits. They default to the entire byte.
    """

    # It seems simplest to extract the entire byte as a bitfield and then slice
    # it.
    bits = "{0:08b}".format(byte)
    return bits[offset:offset+width]

