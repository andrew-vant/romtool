""" Hooks for Pokemon Ruby """

import logging
import re

from romtool.field import StringField

log = logging.getLogger(__name__)

class PokedexName(StringField):
    """ Virtual field extracting the pokemon's name from its desc

    There's a map of species with names to pokedex entries, but not the other
    way around, and no name field in the pokedex itself. Makes life hard.
    Thankfully the pokedex's description field is pretty consistent; the name
    is always(?) all-caps in desc1.
    """
    pattern = re.compile(r'\b[A-Z]+(?:\s+[A-Z]+)*\b')

    def read(self, obj, objtype=None):
        match = self.pattern.search(obj.desc1 + obj.desc2)
        return match and match.group()

    def write(self, obj, value):
        log.debug("can't actually set virtual pokedex 'name' field")

MAP_FIELDS = {'pname': PokedexName}
