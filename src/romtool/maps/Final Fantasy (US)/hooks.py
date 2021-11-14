import logging

from romlib.types import Field, IntField, StructField
from romlib.structures import Structure


_statusbits = 'dspbtlmc'
_elembits = 'sptdfile'
_save_data_offset = 0x400
_save_data_length = 0x400
_save_checksum_offset = 0xFD
log = logging.getLogger(__name__)


class SpellArgument(Field):
    """ Field used for spell effect arguments

    The effectivity field may be either a bitfield (representing either
    statuses or elements) or a scalar (representing spell power). Which it is
    depends on the spell routine the spell uses.
    """
    handles = ['effect']
    _typemap = {0x03: 'statuses',
                0x08: 'statuses',
                0x12: 'statuses',
                0x0A: 'elements'}

    # I feel like there should be a better way to do this.
    def forward(self, methodname, obj, *args, **kwargs):
        if obj.code in self._typemap:
            method = getattr(StructField, methodname)
            realtype = self._typemap[obj.code]
        else:
            method = getattr(IntField, methodname)
            realtype = 'uint'
        log.debug(f"forwarding {self.id}.{methodname} to {method}")
        value = method(self, obj, *args, **kwargs, realtype=realtype)
        if not any([value is None,
                    isinstance(value, int),
                    isinstance(value, Structure)]):
            msg = f"bug: spellarg.read returned bad type: {type(value)}"
            raise AssertionError(msg)
        return value

    def read(self, obj, objtype=None):
        return self.forward('read', obj, objtype)

    def write(self, obj, value):
        self.forward('write', obj, value)

    def parse(self, string):
        return self._realcls(obj).parse(self, string)


def save_checksum(data):
    """ Save file checksum calculation

    `data` should be the data to be summed, not the whole save file. It must be
    iterable; bytes read from a file will do. It will not be modified.

    FF1 saves use the following checksum algorithm: Sum all the bytes in the
    save except the checksum itself, take the result modulo 0xFF, then reverse
    the bits. The checksum is saved at offset 0x4FD in the .SAV. The data
    starts at 0x400 and runs for 0x400 bytes.
    """

    # The checksum ignores its own offset when being calculated; it's simpler
    # to clobber it with zero than special-case it in the calculation, so let's
    # do that.

    data = list(data)
    data[_save_checksum_offset] = 0
    return sum(data) % 0xFF ^ 0xFF


def sanitize_save(savefile):
    """ Update a save file with the correct checksum

    `savefile` should be open in r+b mode.
    """

    # FIXME: Should sanitize character Damage to account for e.g. weapon
    # changes, since it never gets recalculated in-game. But maybe that should
    # be in linter

    savefile.seek(_save_data_offset)
    data = savefile.read(_save_data_length)
    oldsum = data[_save_checksum_offset]
    checksum = save_checksum(data)
    msg = "Updating checksum. Old checksum was 0x%02X, new checksum is 0x%02X"
    logging.info(msg, oldsum, checksum)
    savefile.seek(_save_data_offset + _save_checksum_offset)
    savefile.write(bytes([checksum]))
