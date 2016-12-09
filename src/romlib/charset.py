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

class UnusedSubset(Exception):
    pass

class Subset(object):
    def __init__(self, domain, text):
        try:
            first = next(i for i, c in enumerate(text) if c in domain)
        except StopIteration:
            raise UnusedSubset

        self.string = domain
        self.refidx = first
        self.refchar = text[self.refidx]
        self.reford = ord(self.refchar)
        self.rootchar = domain[0]
        self.rootord = ord(self.rootchar)

class Pattern(object):
    def __init__(self, s):
        self.string = s
        self.length = len(s)


        # Precalculate the first upper, lower and digit character in the
        # string, because we'll need them repeatedly and the scan is
        # surprisingly expensive.
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits[1:]

        self.subsets = []
        for domain in lowercase, uppercase, digits:
            try:
                self.subsets.append(Subset(domain, self.string))
            except UnusedSubset:
                pass

    def buildmap(self, data):
        if len(self.string) != len(data):
            # Happens near EOF
            raise NoMapping("Length mismatch")

        for subset in self.subsets:
            subset.refbyte = data[subset.refidx]
            subset.rootbyte = subset.refbyte - (subset.reford - subset.rootord)
            # Check and reject mappings that go out of bounds. This is a cheap way
            # of detecting most misses.
            if subset.rootbyte < 0 or subset.rootbyte + len(subset.string) > 255:
                raise NoMapping("Mapping would go out of bounds")

        # Check that none of the subsets overlap
        self.subsets.sort(key=lambda ss: ss.rootbyte)
        last = 0
        for subset in self.subsets:
            if subset.rootbyte < last:
               raise NoMapping("Overlapping submaps")
            last = subset.rootbyte + len(subset.string)

        # Build a speculative character set
        charmap = {}
        for subset in self.subsets:
            for i, char in enumerate(subset.string):
                charmap[char] = subset.rootbyte + i

        # Now go down the string. Look for contradictions and add
        # non-contradictions (e.g. punctuation) to the map.
        for char, byte in zip(self.string, data):
            if char not in charmap:
                charmap[char] = byte
            elif charmap[char] != byte:
                raise NoMapping("Contradiction detected")

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
