""" Classes and utilities for building ROM patches."""

import os
import codecs
import itertools
from itertools import repeat

from . import util
from .exceptions import RomtoolError

_IPS_HEADER = "PATCH"
_IPS_FOOTER = "EOF"
_IPS_BOGO_ADDRESS = 0x454f46
_IPS_RLE_THRESHOLD = 10  # How many repeats before trying to use RLE?


class PatchError(RomtoolError):
    """ Exception raised for broken patches """


class PatchFormatError(PatchError):
    """ A patch is 'broken' somehow."""


class PatchValueError(PatchError):
    """ A patch's format is correct but it contains contradictory data."""


class Patch:
    """ A ROM patch."""
    def __init__(self, data=None, rom=None):
        """ Create a Patch.

        data: A dictionary of changes to be made.
        rom: A rom to filter the changes against. Any changes that are
             no-ops will be removed. Note that this is optional and can
             also be done manually with Patch.filter.
        """
        if data is None:
            data = {}
        self.changes = data.copy()
        if rom:
            self.filter(rom)

    def __eq__(self, other):
        return self.changes == other.changes

    @classmethod
    def _blockify(cls, changes):
        """ Convert canonical changes to bytes object changes.

        The idea is to merge adjacent changes into a single change object.
        This would normally be done before writing out a patch so the patch
        is not huge. Romlib's internal format only stores individual byte
        changes because bytes objects are harder to merge, filter, etc.
        """

        merged = {}
        block = bytearray()  # Current block contents.
        start = None         # Start of current block.
        last = None        # Offset of last change seen.
        for offset, value in sorted(changes.items()):
            if start is None:
                # First entry.
                block.append(value)
                start = offset
                last = offset
            elif offset == last + 1:
                # Adjacent change.
                block.append(value)
                last = offset
            else:
                # Nonadjacent change. Store the current change block and start
                # a new one.
                merged[start] = block
                block = bytearray()
                block.append(value)
                start = offset
                last = offset
        if start is not None:
            # Make sure the last block gets merged.
            merged[start] = block
        return merged

    @classmethod
    def from_blocks(cls, blocks):
        """ Load an offset-to-bytes-object dictionary. """
        changes = {}
        for start, data in blocks.items():
            for i, byte in enumerate(data):
                changes[start+i] = byte
        return Patch(changes)

    @classmethod
    def from_ips(cls, f):
        """ Load an ips patch file. """
        # Read and check the header
        header = f.read(5)
        if codecs.decode(header) != _IPS_HEADER:
            raise PatchFormatError("Header mismatch reading IPS file.")

        changes = {}
        while True:
            # Check for EOF marker
            data = f.read(3)
            if data == codecs.encode(_IPS_FOOTER):
                break

            # Start reading a record.
            offset = int.from_bytes(data, 'big')
            size = int.from_bytes(f.read(2), 'big')

            # If size is greater than zero, we have a normal record.
            if size > 0:
                for i, byte in enumerate(f.read(size)):
                    changes[offset+i] = byte

            # If size is instead zero, we have an RLE record.
            else:
                rle_size = int.from_bytes(f.read(2), 'big')
                value = f.read(1)[0]
                for i in range(rle_size):
                    changes[offset+i] = value
        return Patch(changes)

    @classmethod
    def from_ipst(cls, f):
        """ Load an ipst patch file. """

        def parse_line(line):
            """ Parse one line of an ipst file

            Returns an offset and an iterable of byte values to put there.
            Raises an exception if something is wrong with the record.
            """
            # Normal records have three parts, RLE records have four. There's
            # probably a cleaner way to do this.
            parts = line.split(":")
            if len(parts) == 3:
                offset, size, data = parts
                # The size component is optional; it only exists to ease
                # inspecting actual IPS files. If present it must be correct.
                size = size or hex(len(data) // 2)
                length, expected = len(data) // 2, int(size, 16)
                if length != expected:
                    raise ValueError(f"size field ({size}) does not match "
                                     f"data length ({length} bytes)")
                return int(offset, 16), bytes.fromhex(data)
            if len(parts) == 4:
                # For consistency with above, don't enforce the size field
                parts[1] = parts[1] or '0000'
                offset, size, rle_size, value = [int(part, 16)
                                                 for part in parts]
                if value > 0xFF:
                    raise ValueError(f"multi-byte RLE value {value:02X}")
                return offset, repeat(value, rle_size)
            raise ValueError("expected 3-4 colon-separated fields")

        # Ignore comments and trailing whitespace; note line numbers. The
        # first real line must be a valid header. Each subsequent real line
        # must be a valid IPS record. When we hit the footer, stop.
        changes = {}
        lines = enumerate((line.partition('#')[0].rstrip() for line in f), 1)
        if next((line for i, line in lines if line), None) != _IPS_HEADER:
            raise PatchFormatError("IPST header malformed or missing")
        for i, line in lines:  # reuse iterator to keep line numbering
            if not line:
                continue
            if line == _IPS_FOOTER:
                break
            try:
                offset, data = parse_line(line)
            except ValueError as ex:
                raise PatchValueError(f"Error on line {i}: {ex}") from ex
            for i, value in enumerate(data):
                changes[offset+i] = value
        else:
            raise PatchFormatError("IPST footer malformed or missing")
        return Patch(changes)

    @classmethod
    def from_diff(cls, original, modified):
        """ Create a patch by diffing a modded rom against the original.

        original: The original ROM, opened in binary mode.
        modified: A verion of the ROM containing the desired modifications.
        """
        lzip = itertools.zip_longest  # convenience alias
        old = original.read()
        new = modified.read()
        patch = Patch()

        for i, (byte1, byte2) in enumerate(lzip(old, new, fillvalue=0)):
            if byte2 != byte1:
                patch.changes[i] = byte2
        return patch

    def _ips_sanitize_changes(self, bogobyte=None):
        """ Check for bogoaddr issues and return merged/fixed changes.

        This is a helper function for writing variants of IPS.

        FIXME: We should split up blocks that include both a RLE-appropriate
        segment and a normal segment. Careful how this interacts with bogoaddr.
        """
        # Merge blocks of changes.
        blocks = self._blockify(self.changes)

        # Deal with bogoaddress issues.
        if _IPS_BOGO_ADDRESS in blocks:
            if bogobyte is None:
                msg = ("A change started at 0x454F46 (EOF) "
                       "but a valid bogobyte was not provided.")
                raise PatchValueError(msg)
            data = blocks.pop(_IPS_BOGO_ADDRESS)
            bogo = bogobyte.to_bytes(1, "big")
            blocks[_IPS_BOGO_ADDRESS-1] = bogo + data
        return blocks

    def to_ips(self, f, bogobyte=None):
        """ Create an ips patch file."""
        blocks = self._ips_sanitize_changes(bogobyte)
        f.write(_IPS_HEADER.encode())
        for offset, data in sorted(blocks.items()):
            # Use RLE if we have a long repetition
            if len(data) > 3 and len(set(data)) == 1:
                f.write(offset.to_bytes(3, 'big'))
                f.write(bytes(2))  # Size is zero for RLE
                f.write(len(data).to_bytes(2, 'big'))
                f.write(data[0:1])
            else:
                f.write(offset.to_bytes(3, 'big'))
                f.write(len(data).to_bytes(2, 'big'))
                f.write(data)
        f.write(_IPS_FOOTER.encode())

    def to_ipst(self, f, bogobyte=None):
        """ Create an ipst patch file."""
        blocks = self._ips_sanitize_changes(bogobyte)
        print(_IPS_HEADER, file=f)
        for offset, data in sorted(blocks.items()):
            # Use RLE if we have a long repetition
            if len(data) > 3 and len(set(data)) == 1:
                fmt = "{:06X}:{:04X}:{:04X}:{:01X}"
                print(fmt.format(offset, 0, len(data), data[0]), file=f)
            else:
                datastr = ''.join(f'{d:02X}' for d in data)
                fmt = "{:06X}:{:04X}:{}"
                print(fmt.format(offset, len(data), datastr), file=f)
        print(_IPS_FOOTER, file=f)

    def filter(self, rom):
        """ Remove no-ops from the change list.

        This compares the list of changes to the contents of a ROM and
        filters out any data that is already present."""
        def getbyte(f, offset):
            """ Convenience function to get a single byte from a file."""
            f.seek(offset)
            return f.read(1)[0]

        self.changes = {offset: value for offset, value in self.changes.items()
                        if value != getbyte(rom, offset)}

    def apply(self, f):
        """ Apply a patch to a file object.

        The file should be opened with mode "r+b".
        """
        for offset, block in self._blockify(self.changes).items():
            f.seek(offset)
            f.write(block)

    def save(self, outfile, ptype=None):
        """ Save a patch to a file.

        This detects the type of patch from the filename extension. You can
        override detection by supplying ptype.
        """
        if ptype is None:
            # Take the extension of the filename and strip the leading dot.
            ptype = os.path.splitext(outfile)[-1][1:]
        pfunc = getattr(self, "to_"+ptype)
        mode = 'wt' if ptype.endswith('t') else 'wb'
        with util.flexopen(outfile, mode) as f:
            pfunc(f)

    @classmethod
    def load(cls, patchfile, ptype=None):
        """ Load a patch given a filename.

        This detects the type of patch from the filename extension. You can
        override detection by supplying ptype.
        """
        if ptype is None:
            # Take the extension of the filename and strip the leading dot.
            ptype = os.path.splitext(patchfile)[-1][1:]
        pfunc = getattr(cls, "from_"+ptype)
        mode = 'rt' if ptype.endswith('t') else 'rb'
        with util.flexopen(patchfile, mode) as f:
            patch = pfunc(f)
        return patch
