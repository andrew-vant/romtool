#!/usr/bin/python3

import sys
import logging
import string
import itertools
from pprint import pprint

# Given a string and a byte stream, how do I know if it matches?
#
# Take all lowercase letters. Ensure they differ from each other in the manner
# one would expect. Repeat for uppercase letters. Repeat for digits. If all
# that matches, we have a hit. Create a dict mapping letters and symbols to
# bytes based on this bytestream and record it.

# Compare such mappings for
# multiple strings to get better accuracy and fill in additional characters; if
# there's a mismatch, something is wrong. If there isn't, we have most of our
# map, but probably not our terminator character.

class NoMapping(Exception):
    pass

class MappingConflictError(Exception):
    pass

class Pattern(object):
    def __init__(self, s):
        self.string = s
        self.length = len(s)


        # Precalculate the first upper, lower and digit character in the
        # string, because we'll need them repeatedly and the scan is
        # surprisingly expensive.
        self.subsets = []
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits[1:]
        first = lambda x, subset: next((i for i, c in enumerate(subset)), None)
        for subset in lowercase, uppercase, digits:
            try:
                first = next(i for i, c in enumerate(s) if c in subset)
            except StopIteration:
                pass
            else:
                self.subsets.append((subset, first, s[first]))

    def buildmap(self, data):
        if len(self.string) != len(data):
            # Happens near EOF
            raise NoMapping()

        subsets = []
        for subset, refpoint, refchar in self.subsets:
            refbyte = data[refpoint]
            root = refbyte - (ord(refchar) - ord(subset[0]))
            subsets.append((subset, refpoint, refchar, refbyte, root))

            # Check and reject mappings that go out of bounds. This is a cheap way
            # of detecting most misses.
            if root < 0 or root + len(subset) > 255:
                raise NoMapping("Mapping would go out of bounds")

        # Check that none of the subsets overlap
        subsets.sort(key=lambda t: t[-1])
        last = 0
        for subset, refpoint, refchar, refbyte, root in subsets:
            if root < last:
               raise NoMapping("Overlapping submaps")
            last = root + len(subset)

        # Build a speculative character set
        charmap = {}
        for subset, refpoint, refchar, refbyte, root in subsets:
            for i, char in enumerate(subset):
                charmap[char] = root + i

        # Now go down the string. Look for contradictions and add
        # non-contradictions (e.g. punctuation) to the map.
        for char, byte in zip(self.string, data):
            if char not in charmap:
                charmap[char] = byte
            elif charmap[char] != byte:
                raise NoMapping

        # If we get here, we have a consistent and mostly-complete map.
        return charmap

def merge(*dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            if k in out and v != out[k]:
                msg = "%s mapped as both %s and %s"
                raise MappingConflictError(msg, k, v, out[k])
            else:
                out[k] = v
    return out
