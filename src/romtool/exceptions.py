""" Romlib exceptions """

class RomtoolError(Exception):
    """ Base class for romtool exceptions """

class RomError(RomtoolError):
    """ Exception raised for broken ROMs """

class MapError(RomtoolError):
    """ Exceptions involving broken map definitions """

class ChangesetError(RomtoolError):
    """ Exception raised for broken changesets """
