from bitstring import Bits

class IPSPatch(object):
    header = "PATCH".encode("ascii")
    footer = "EOF".encode("ascii")

    def __init__(self, changes):
        if 0x454f46 in changes:
            raise NotImplementedError("0x454f46/EOF workaround not yet implemented.")
        self.records = sorted(changes.items())

    def write(self, f):
        recordbytes = b""
        for offset, data in self.records:
            # Each record is a three-byte big-endian integer indicating the record's
            # offset, followed by a two-byte big-endian integer indicating its size,
            # followed by the data to be inserted.
            # FIXME: Probably all sorts of ValueErrors should be checked for here...
            recordbytes += Bits(uintbe=offset, length=24).bytes
            recordbytes += Bits(uintbe=len(data), length=16).bytes
            recordbytes += data
        f.write(self.header + recordbytes + self.footer)
