""" Romtool hooks for FF1. """

import logging

from romtool.field import IntField


_SAVE_DATA_OFFSET = 0x400
_SAVE_DATA_LENGTH = 0x400
_SAVE_CHECKSUM_OFFSET = 0xFD
log = logging.getLogger(__name__)


class SpellArgument(IntField):
    """ Field used for spell effect arguments

    The effectivity field may be either a bitfield (representing either
    statuses or elements) or a scalar (representing spell power). Which it is
    depends on the spell routine the spell uses.
    """
    # Map spell codes to union fields
    _typemap = {0x03: 'statuses',
                0x08: 'statuses',
                0x12: 'statuses',
                0x0A: 'elements'}

    def _realtype(self, obj):
        tp_name = self._typemap.get(obj.func)
        return obj.root.map.structs[tp_name] if tp_name else int

    def read(self, obj):
        view = self.view(obj)
        _type = self._realtype(obj)
        return view.uint if _type is int else _type(view, obj)

    def write(self, obj, value):
        view = self.view(obj)
        _type = self._realtype(obj)
        if _type is int:
            view.uint = value
        else:
            target = self.read(obj)
            update = target.parse if isinstance(value, str) else target.copy
            update(value)


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
    data[_SAVE_CHECKSUM_OFFSET] = 0
    return sum(data) % 0xFF ^ 0xFF


def sanitize_save(savefile):
    """ Update a save file with the correct checksum

    `savefile` should be open in r+b mode.
    """

    # FIXME: Should sanitize character Damage to account for e.g. weapon
    # changes, since it never gets recalculated in-game. But maybe that should
    # be in linter

    savefile.seek(_SAVE_DATA_OFFSET)
    data = savefile.read(_SAVE_DATA_LENGTH)
    oldsum = data[_SAVE_CHECKSUM_OFFSET]
    checksum = save_checksum(data)
    msg = "Updating checksum. Old checksum was 0x%02X, new checksum is 0x%02X"
    log.info(msg, oldsum, checksum)
    savefile.seek(_SAVE_DATA_OFFSET + _SAVE_CHECKSUM_OFFSET)
    savefile.write(bytes([checksum]))


MAP_FIELDS = {'effect': SpellArgument}
