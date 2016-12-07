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

        self.lowers =  [char if char.islower() else None
                        for char in s]
        self.uppers =  [char if char.isupper() else None
                        for char in s]
        self.numbers = [char if char in string.digits else None
                        for char in s]
        self.other =   [char if not char.isalnum() else None
                        for char in s]

    def buildmap(self, data):
        if len(self.string) != len(data):
            # Happens near EOF
            raise NoMapping()

        charmap = {}

        # Assume the first digit, lowercase, and uppercase character are all
        # accurate; build a speculative map based on those and assuming each
        # character subset is contiguous. Then look for contradictions.

        subsets = (string.ascii_lowercase,
                   string.ascii_uppercase,
                   string.digits[1:]) # Zero might be on either end

        for subset in subsets:
            try:
                refchar, refbyte = next((c, b) for c, b
                                        in zip(self.string, data)
                                        if c in subset)
            except StopIteration:
                pass
            else:
                # My head hurts
                root = subset.index(refchar)
                for i, char in enumerate(subset):
                    byte = refbyte - (root - i)
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
