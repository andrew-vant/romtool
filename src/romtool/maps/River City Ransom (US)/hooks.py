""" Romtool hooks for RCR """

import logging

from romtool.field import IntField
from romtool.io import Unit


log = logging.getLogger(__name__)


class Buff(IntField):
    """ Field representing an item stat buff

    The item structure contains a bitfield flagging which stats the item
    buffs. At the tail of the item structure is an array of bytes, one per
    buffed stat, indicating how much to buff each stat.
    """
    def _offset(self, obj):
        flags = obj.buffs
        offset = len(obj.name) + 1 + 8  # name, plus EOS, plus previous fields
        log.debug("sorting flags for %s", obj.name)
        for field in flags.fields:
            log.debug("field offset check: %s %s", field.offset.eval(obj), field.id)
            if getattr(flags, field.id):
                if field.id == self.id:
                    return offset
                offset += 1
        return None

    def view(self, obj):
        offset = self._offset(obj)
        return obj.view[offset:offset+1:Unit.bytes] if offset else None

    def read(self, obj, realtype=None):
        view = self.view(obj)
        return view and view.int

    def write(self, obj, value, realtype=None):
        value = value or None
        old = self.read(obj)
        if isinstance(value, str):
            value = int(value, 0)
        if value != old:
            raise NotImplementedError(f"can't change item buffs yet ({value!r} != {old!r})")
            # pretty sure writing any item buff requires rewriting all of them



MAP_FIELDS = {'buff': Buff}
