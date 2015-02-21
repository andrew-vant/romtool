from bitstring import Bits

class IPSPatch(object):
    header = "PATCH".encode("ascii")
    footer = "EOF".encode("ascii")
    bogoaddr = 0x454f46

    def __init__(self, changes, bogobyte = None):
        self.records = []
        self.bogobyte = bogobyte

        for offset, data in sorted(changes.items()):
            if len(self.records) == 0:
                self.records.append((offset, data))
                continue
            lastoffset, lastdata = self.records[-1]
            if lastoffset + len(lastdata) == offset:
                self.records[-1] = (lastoffset, lastdata + data)
                continue
            self.records.append((offset, data))

        for i, (offset, data) in enumerate(self.records):
            if offset == self.bogoaddr:
                if bogobyte is None:
                    raise ValueError("A change started at 0x454f46 (EOF) "
                                     "but bogobyte was not provided.")
                else:
                    # Kick back the record starting at the bad address one byte.
                    # This should always be safe, because if there was something
                    # at the previous byte, concatenation would have occurred.
                    self.records[i] = (offset - 1, bytes([bogobyte]) + data)


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
