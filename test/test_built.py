""" Test for presence of build-time extras

e.g. version and nointro files need to be included in the sdist because they
can't be generated without supporting files (or the git repo)
"""

import os
import unittest

import romtool.util as util

class TestBuiltModules(unittest.TestCase):
    def test_version(self):
        # Not sure how to do this right. In particular, I don't know how
        # building from the sdist (i.e. from pip, at install time) will work
        # when the git repo isn't present.
        try:
            from romtool.version import version
        except ImportError as ex:
            self.fail(str(ex))
    def test_nointro(self):
        # Just check that we get some non-zero number of roms...
        self.assertTrue(len(util.nointro()))
