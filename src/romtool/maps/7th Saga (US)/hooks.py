""" Romtool hooks for 7th Saga. """

from romtool.rom import SNESRom
from romtool.util import ChainView


class Rom(SNESRom):
    """ A 7th Saga ROM. """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The weapon, armor, and item indexes are consecutive, and collectively
        # form one big table. Item cross-references are often indices to the
        # overall table rather than a particular subset, making resolving them
        # difficult; a reference to table index #30 is an item, while a
        # reference to table index #104 is a weapon.
        sources = [self.root.entities[k]
                   for k in ['items', 'weapons', 'armor']]
        self.tables['loot'] = ChainView(*sources)
