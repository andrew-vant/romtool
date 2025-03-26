""" Romlib exceptions """

import logging


log = logging.getLogger(__name__)


class RomtoolError(Exception):
    """ Base class for romtool exceptions """

class RomError(RomtoolError):
    """ Exception raised for broken ROMs """

class MapError(RomtoolError):
    """ Exceptions involving broken map definitions

    The optional `source` argument indicates where in the map the error
    occurred (for example, which structure or field definition). The intent is
    for it to act as a sort of dot-path to which a series of except blocks can
    add whichever elements are locally known before re-raising.

    If `source` is given, `msg` should be only the cause of the error --
    usually another exception's message string. A standard-ish error message
    can be generated from these. If only `msg` is given, it will be used
    as-is.
    """
    def __init__(self, msg, source=None):
        self.args = (msg, source)
        self.msg = msg
        self.source = source

    def __str__(self):
        return (self.msg if not self.source
                else f"map error in {self.source} definition: {self.msg}")


class ChangesetError(RomtoolError):
    """ Exception raised for broken changesets """

class RomDetectionError(RomtoolError):
    """ Indicates that we couldn't autodetect the map to use for a ROM.

    Supply the unknown hash and the offending file. The latter may be either
    a path-like object or an open file.
    """
    def __init__(self, _hash=None, file=None):
        super().__init__()
        self.hash = _hash
        self.file = getattr(file, 'name', file)

    def __str__(self):
        return "ROM sha1 hash not in db: {}".format(self.hash)

    def log(self):
        log.error("Couldn't autodetect ROM map for %s", self.file)
        log.error("%s", self)
        log.error("The rom may be unsupported, or your copy may "
                      "be modified, or this may be a save file")
        log.error("You will probably have to explicitly supply --map")
