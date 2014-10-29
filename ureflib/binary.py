import logging

class BinaryException(Exception):
    pass

class BinaryRangeException(Exception):
    pass

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

