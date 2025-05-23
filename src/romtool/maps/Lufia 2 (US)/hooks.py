""" Romtool hooks for Lufia 2. """

import logging

from romtool.field import IntField
from romtool.io import Unit
from romtool.util import HexInt


log = logging.getLogger(__name__)


class MonsterExtra(IntField):
    """ Field used for monster "tail options"

    At the end of the monster structure are up to three optional fields
    defining the monster's drops, combat script, and resistances. Each set
    consists of a  one-byte type indicator followed by a two-byte value. The
    type indicator has three known values: 0x03 (drop item/chance), 0x07
    (script pointer), and 0x08 (resist pointer). 0x00 means stop. The fields,
    if present, always appear in this order.

    Monsters with no drop field never drop anything; monsters with no script
    pointer only attack; monsters with no resist pointer have neutral resists.
    """

    known_extypes = [0x03, 0x07, 0x08]

    # FIXME: Is there a way to alter a logger within the main dump/load loop
    # such that it can print the index of the monster being processed even if
    # the function logging the message does not know it?

    @classmethod
    def _extras(cls, obj):
        tail = obj.view[33:33+9:Unit.bytes]  # up to nine tail bytes
        for i in range(3):
            extype = tail.bytes[i*3]
            if not extype:
                return
            if extype not in cls.known_extypes:
                log.warning("Unknown monster extype found: 0x%.2X", extype)
            sl = slice(3*i+1, 3*i+3, Unit.bytes)
            yield extype, tail[sl]

    def _view(self, obj):
        view = next((view for extype, view
                     in self._extras(obj)
                     if extype == self.arg),
                    None)
        if view is None:
            return None
        start = self.offset.eval(obj)
        end = start + (self.size.eval(obj) * self.unit)
        return view[start:end]

    def read(self, obj, realtype=None):
        view = self._view(obj)
        if view is None:
            return None
        value = view.uint
        if self.display in ('hex', 'pointer'):
            value = HexInt(value, len(view))
        return value

    def write(self, obj, value, realtype=None):
        # Probably this conversion should happen elsewhere...
        value = None if value == '' else value
        view = self._view(obj)
        fid = self.id
        name = self.name

        if view is None and value is None:
            return  # Nothing to do
        if value == self.read(obj):
            return  # Still nothing to do
        if view is None and value is not None:
            msg = f"Can't safely add {fid} ({name}) to a monster yet"
            raise NotImplementedError(msg)
        if view is not None and value is None:
            msg = f"Can't safely remove {fid} ({name}) from a monster (yet)"
            raise NotImplementedError(msg)
        view.uint = value

    def parse(self, string):
        return int(string, 0) if string else None


MAP_FIELDS = {'exmon': MonsterExtra}
