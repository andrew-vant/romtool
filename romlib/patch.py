import binascii
import io
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

    @classmethod
    def textualize(cls, infile, outfile):
        """ Convert an IPS patch to a readable text format.

        Note that this intentionally does not validate the structure of the
        input file. This is so you can see and possibly manually repair errors.
        """

        # Not sure if I should do my own seeking here or assume the caller did
        # the right thing....
        infile.seek(0)
        outfile.seek(0)

        # Convert the header
        print(infile.read(5).decode(), file=outfile)

        # Read and print records until we hit EOF.
        while True:
            offset_raw = infile.read(3)

            if offset_raw == b'EOF':
                print("EOF", file=outfile)
                continue # Allow brokenness, e.g. bogobyte.

            if not offset_raw:
                break # End of file

            size_raw = infile.read(2)
            size = int.from_bytes(size_raw, 'big')
            # If size is zero, we're dealing with an RLE record.
            repeat_raw = None if size else infile.read(2)
            repeat = None if size else int.from_bytes(repeat_raw, 'big')
            data_raw = infile.read(size) if size else infile.read(1)

            # Data and offset need some massaging to get output strings.
            data_str = binascii.hexlify(data_raw).decode().upper()
            offset_str = binascii.hexlify(offset_raw).decode().upper()

            if repeat is None:
                line = "0x{}:{}:{}".format(offset_str, size, data_str)
                print(line, file=outfile)
            else:
                line = "0x{}:!{}:{}".format(offset_str, repeat, data_str)
                print(line, file=outfile)


    @classmethod
    def compile(cls, infile, outfile):
        infile.seek(0)
        outfile.seek(0)

        lines = (line.rstrip("\n") for line in infile)
        for line in lines:
            # Skip comments and blank lines
            if not line or line.startswith("#"):
                continue

            # Lines that aren't records get output as-is.
            if ":" not in line:
                outfile.write(line.encode())
                continue

            # Split a record line on a colon delimiter, interpret, and write it.
            offset, size, data = line.split(":")
            repeat = None
            if size.startswith("!"):
                repeat = size[1:]
                size = "0"

            outfile.write(bytearray.fromhex(offset[2:]))
            outfile.write(int(size, 0).to_bytes(2, 'big'))
            if repeat:
                outfile.write(int(repeat, 0).to_bytes(2, 'big'))
            outfile.write(bytearray.fromhex(data))
