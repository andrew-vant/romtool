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
    
    # Sanity check the size of the number we're loading.
    if byte > 255:
        raise BinaryRangeException(
            "Tried to unpack a tinyint that isn't tiny. Value: {}", byte)

    # Sanity check bit order. 
    bitorder = bitorder.lower()
    if bitorder not in ["big","little"]:
        raise BinaryException("'{}' is not a bit ordering.", bitorder)

    # Figure out which bits are set. This method for checking bits produces
    # a list starting from the right, but we need it from the left, so reverse
    # it. 
    bitlist = [byte & 2**bit != 0 for bit in range(8)]
    bitlist.reverse()
    
    # Slice out the bits we're interested in.
    bits = bitlist[offset:width]
    
    # We're going to use the same method as above to calculate the value, and
    # again it wants to start from the right, so if we have bits in big endian
    # order (which we probably do), reverse them again. 
    if bitorder == "big":
        bits.reverse()

    # Do the math. 
    return sum(2**i for i in range(width) if bits[i])

def unpack_flag(byte, offset):
    """ Extract a one-bit flag from a byte. Returns a bool. """
    return (byte & (1 << offset)) != 0

def unpack_bitfield(byte, offset = 0, width = 8):
    """ Return a string representing a bitfield.
    
    Offset and width are expressed in bits. They default to the entire byte.
    """
    
    # It seems simplest to extract the entire byte as a bitfield and then slice
    # it.
    bits = "{0:08b}".format(byte)
    return bits[offset:offset+width]

