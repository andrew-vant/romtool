""" Romlib exceptions """

import logging


log = logging.getLogger(__name__)


class RomtoolError(Exception):
    """ Base class for romtool exceptions """

class RomError(RomtoolError):
    """ Exception raised for broken ROMs """

class MapError(RomtoolError):
    """ Exceptions involving broken map definitions """

class ChangesetError(RomtoolError):
    """ Exception raised for broken changesets """

class RomDetectionError(RomtoolError):
    """ Indicates that we couldn't autodetect the map to use for a ROM."""
    def __init__(self, _hash=None, filename=None):
        super().__init__()
        self.hash = _hash
        self.filename = filename
    def __str__(self):
        return "ROM sha1 hash not in db: {}".format(self.hash)
    def log(self):
        log.error("Couldn't autodetect ROM map for %s", self.filename)
        log.error("%s", self)
        log.error("The rom may be unsupported, or your copy may "
                      "be modified, or this may be a save file")
        log.error("You will probably have to explicitly supply --map")
