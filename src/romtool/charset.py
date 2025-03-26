""" An incredibly stupid attempt to detect unknown charsets.

Everything about this module is terrible. It was intended to ease figuring
out the character sets of games. It *sort of* does that, but it's badly
designed, badly commented, slow, and quite possibly a fundamentally misguided
idea in the first place. The right way to do this is almost certainly to
visually inspect the rom for a font-like bitmap and go from there.

To the extent that this functions at all, it does so by looking for byte
sequences in which the diffs between bytes match the diffs between characters
in the input string.
"""
# FIXME: either make this module not suck, or rip it out.

import string
from dataclasses import dataclass


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
    """ Mo possible mapping fits the given data. """

class MappingConflictError(Exception):
    """ More than one character maps to the same byte. """

class UnusedSubset(Exception):
    """ A given character subset doesn't appear in a pattern. """

@dataclass
class Subset:  # pylint: disable=too-many-instance-attributes
    """ A subset of a potential character mapping.

    Helper class for pattern checking. Precalculates the ordinal diffs of
    each character in a pattern string from the first character in the
    `domain` string. The domain is expected to be lowercase, uppercase, or
    digit characters, as provided by std.string. The underlying intuition
    is that uppercase characters are likely to be contiguous in almost any
    character map, and the same is true for lowercase and digits, but no
    assumptions can be made about contiguity between the three subsets of
    possible characters.

    Also records some related data useful for consistency checks.
    """
    domain: str
    text: str

    def __post_init__(self):
        try:
            first = next(i for i, c in enumerate(self.text)
                         if c in self.domain)
        except StopIteration as ex:
            raise UnusedSubset from ex

        self.string = self.domain
        self.slen = len(self.string)
        self.refidx = first
        self.refchar = self.text[self.refidx]
        self.reford = ord(self.refchar)
        self.rootchar = self.domain[0]
        self.rootord = ord(self.rootchar)

        self.rootdiffs = [self.domain.find(c) for c in self.text]
        self.rootdiffs = [(i if i != -1 else None) for i in self.rootdiffs]


class Pattern:  # pylint: disable=too-few-public-methods
    """ A known string to look for in ROM data."""
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

    def _refpoints(self, data):
        for subset in self.subsets:
            refbyte = data[subset.refidx]
            rootbyte = refbyte - (subset.reford - subset.rootord)
            # Check and reject mappings that go out of bounds. This is a
            # cheap way of detecting many misses.
            if rootbyte < 0 or rootbyte + subset.slen > 255:
                raise NoMapping("Mapping would go out of bounds")
            subset.refbyte = refbyte
            subset.rootbyte = rootbyte

    def _overlapcheck(self):
        # Check that none of the subsets overlap
        self.subsets.sort(key=lambda ss: ss.rootbyte)
        last = 0
        for subset in self.subsets:
            if subset.rootbyte < last:
                raise NoMapping("Overlapping submaps")
            last = subset.rootbyte + len(subset.string)

    def _diffcheck(self, data):
        for i, byte in enumerate(data):
            for subset in self.subsets:
                diff = subset.rootdiffs[i]
                if diff is None:
                    continue
                if byte - diff != subset.rootbyte:
                    raise NoMapping("Diff failure")

    def _speculativecharset(self):
        # Build a speculative character set
        charset = {}
        for subset in self.subsets:
            for i, char in enumerate(subset.string):
                charset[char] = subset.rootbyte + i
        return charset

    def _contradictioncheck(self, data, charset):
        # Now go down the string. Look for contradictions and add
        # non-contradictions (e.g. punctuation) to the map.
        for char, byte in zip(self.string, data):
            if char not in charset:
                charset[char] = byte
            elif charset[char] != byte:
                raise NoMapping("Contradiction detected")


    def buildmap(self, data):
        """ Try to build a character map mapping this pattern to input data.

        Returns a dictionary mapping characters to bytes. Raises NoMapping if
        no consistent map is possible.
        """
        self._refpoints(data)
        self._diffcheck(data)
        self._overlapcheck()
        charset = self._speculativecharset()
        self._contradictioncheck(data, charset)
        # If we get here, we have a consistent and mostly-complete map.
        return charset

def merge(*dicts):
    """ Merge character-map subsets and check them for conflicts. """
    out = {}
    for d in dicts:
        for k, v in d.items():
            if k in out and v != out[k]:
                msg = "%s mapped as both %s and %s"
                raise MappingConflictError(msg, k, v, out[k])
            out[k] = v
    return out
