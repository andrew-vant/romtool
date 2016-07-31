""" Monkeypatch bitstring with extra types.

This adds a few romlib-specific types to bitstring so that bs constructors know
what to do with them. The idea is to make auto initializers and splatted
dictionary args work.
"""
import sys
import inspect
import re

import bitstring

from . import util


def monkeypatch(module=None):
    """ Introduce romlib types into bitstring module."""

    if not module:
        module = bitstring
    prefixes = '_read_', '_set_'
    # These need to be updated for new types to be recognized.
    initnames = list(module.INIT_NAMES)
    token_re = module.TOKEN_RE

    for prefix in prefixes:
        funcs = [(fname, func) for fname, func
                 in vars(sys.modules[__name__]).items()
                 if fname.startswith(prefix)]

        for fname, func in funcs:
            # Insert the function into the bitsring.Bits class.
            typename = fname[len(prefix):]
            if typename not in initnames:
                initnames.append(typename)
            setattr(module.Bits, fname, func)
            method = getattr(module.Bits, fname)

            # Add it to the appropriate constructor lookup table.
            sig = inspect.signature(func)
            if 'read' in prefix:
                module.name_to_read[typename] = method
            elif 'length' in sig.parameters and 'offset' in sig.parameters:
                module.init_with_length_and_offset[typename] = method
            elif 'length' in sig.parameters:
                module.init_with_length_only[typename] = method
            else:
                module.init_without_length_or_offset[typename] = method

    module.INIT_NAMES = initnames
    module.TOKEN_RE = re.compile(r'(?P<name>' + '|'.join(initnames) +
                                 r')((:(?P<len>[^=]+)))?(=(?P<value>.*))?$',
                                 re.IGNORECASE)


def _read_lbin(self, length, start):
    s = self._readbin(length, start)
    return util.lbin_reverse(s)


def _set_lbin(self, lbinstring):
    module = sys.modules[self.__module__]
    lbinstring = module.tidy_input_string(lbinstring)
    lbinstring = lbinstring.replace('0b', '')
    binstring = util.lbin_reverse(lbinstring)
    self._setbin_unsafe(binstring)

def _read_union(self, length, start):
    return self[start:length+1]
