import logging

from bitstring import BitStream

from .primitives import Int, Flag

log = logging.getLogger(__name__)


# TODO: Each 'type' needs to be able to read/write from string, stream, and
# value from parent type. Read/write/str/parse on the primitive type?

class Stream(BitStream):
    def read_int(self, tid, sz_bits, mod, display):
        if not mod:  # Catch None and empty strings
            mod = 0
        bstype = tid
        i = super().read(f'{bstype}:{sz_bits}')
        i += mod
        return Int(i, sz_bits, display)

    def read_flag(self, tid, sz_bits, mod, display):
        if sz_bits > 1:
            raise ValueError("Flags must be a single bit")
        f = super().read('bool')
        return Flag(f, sz_bits, display)

    def read_str(self, tid, sz_bits, mod, display):
        return super().read(sz_bits).bytes.decode(display)

    def write_int(self, i, tid, sz_bits, mod, display):
        if not mod:
            mod = 0
        bstype = tid
        i -= mod
        self.overwrite(f'{bstype}:{sz_bits}={i}')

    def write_flag(self, v, tid, sz_bits, mod, display):
        if sz_bits > 1:
            raise ValueError("Flags must be a single bit")
        self.overwrite(f'bool:1={v}')

    def write_str(self, s, tid, sz_bits, mod, display):
        """ Write a fixed-length string

        Undersized strings will be padded with spaces.
        """
        s = s.ljust(sz_bits // 8)
        self.write_strz(s, tid, sz_bits, mod, display)

    def write_strz(self, s, tid, sz_bits, mod, display):
        """ Write a variable-length string """

        pos = self.pos
        old = self.read_str(tid, sz_bits, mod, display)

        if old == s:
            log.debug("Not writing unchanged string: %s", s)
        else:
            self.pos = pos
            self.overwrite(s.encode(display))

    def read(self, tid, sz_bits, mod, display):
        reader = (self.read_int if 'int' in tid
                  else getattr(self, f'read_{tid}'))
        return reader(tid, sz_bits, mod, display)

    def write(self, value, tid, sz_bits, mod, display):
        writer = (self.write_int if 'int' in tid
                  else getattr(self, f'write_{tid}'))
        writer(value, tid, sz_bits, mod, display)
