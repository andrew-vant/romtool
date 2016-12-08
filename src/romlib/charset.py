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

        charmap = {}

        for subset, i, refchar in self.subsets:
            refbyte = data[i]
            root = refbyte - (ord(refchar) - ord(subset[0]))

            # My head hurts
            for i, char in enumerate(subset):
                byte = root + i
                assert(char not in charmap)
                if byte in charmap.values():
                    raise NoMapping("Same byte mapped twice")
                else:
                    charmap[char] = byte

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
