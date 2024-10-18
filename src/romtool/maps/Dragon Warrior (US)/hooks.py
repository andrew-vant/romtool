import logging
from functools import partial
from itertools import islice

from romtool.structures import Table
from romtool.util import SequenceView

log = logging.getLogger(__name__)


class Names(Table):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nm1 = self.root.tables[f"{self.spec.id}_nm1"]
        self._nm2 = self.root.tables[f"{self.spec.id}_nm2"]

    def __iter__(self):
        rom = self.root
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
