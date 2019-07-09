from os.path import realpath, dirname
from os.path import join as pathjoin

def whereami(path):
    """ Get the full path to the containing directory of a file.

    Intended to be called with __file__, mostly
    """
    # FIXME: should this go in util? Maybe not, nothing in romlib uses it.
    return dirname(realpath(path))

def pkgfile(filename):
    return pathjoin(whereami(__file__), filename)
