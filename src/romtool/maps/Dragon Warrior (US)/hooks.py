""" Romtool hooks for Dragon Warrior. """

import logging
from itertools import islice

from romtool.structures import Table
from romtool.util import SequenceView

log = logging.getLogger(__name__)


class Names(Table):
    """ Interface to the name table.

    Names appear in the rom as a long series of variable-length
    null-terminated strings, organized in part by type-of-name (weapon,
    armor, monster, etc), and also by firstname/lastname -- that is, there's
    one list of monster first names, and a completely separate list of
    monster last names for those monsters that have two-word names. Yes, that
    is stupid.

    This class hides the firstname/lastname business so you can treat them as
    a single string.

    The game appears to find name N by scanning through strings until passing
    N string terminators. It is not clear whether it starts the scan from the
    beginning of the global name table, or from the section of the table
    specific to the type of thing being looked up -- i.e. I’m not whether
    shortening, say, the weapon list, will throw off whatever looks up armor
    names.

    Monster names should be safe to change because there are no
    strings immediately following the monster list. Anything else is still
    questionable.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nm1 = self.root.tables[f"{self.spec.id}_nm1"]
        self._nm2 = self.root.tables[f"{self.spec.id}_nm2"]

    def __iter__(self):
        return (' '.join(nm_parts).strip() for nm_parts
                in zip(self._nm1, self._nm2))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        return next(islice(self, i, None))

    def __setitem__(self, i, v):
        nm1, _, nm2 = v.partition(" ")
        self._nm1[i] = nm1.strip()
        self._nm2[i] = nm2.strip()

    def update(self, mapping):
        nm1 = {}
        nm2 = {}
        for i, name in mapping.items():
            first, _, last = name.partition(" ")
            nm1[i] = first
            nm2[i] = last
        self._nm1.update(nm1)
        self._nm2.update(nm2)
