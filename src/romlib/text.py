""" Implements ROM text tables.

The accepted format is defined in Nightcrawler's "Text Table Format" standard.

I would be *really* happy if I could implement this using python's built in
codec capabilities.
"""

import re
import codecs
import logging
import functools

from patricia import trie

log = logging.getLogger(__name__)

class TextTable(object):
    """ A ROM text table, used for decoding and encoding text strings."""
    def __init__(self, name, f):
        self.id = None  # pylint: disable=invalid-name
        self.name = name
        self.enc = trie()
        self.dec = trie()
        self.eos = []

        # Skip blank lines when reading.
        lines = [line for line
                 in f.read().split("\n")
                 if line]

        for line in lines:
            prefix = line[0]
            if prefix in "@/$!":
                line = line[1:]
            if prefix == "@":
                self.id = line
                continue
            if prefix == "!":
                msg = "Table switching not yet implemented."
                raise NotImplementedError(msg)

            code, text = line.split("=", 1)
            codeseq = bytes.fromhex(code)
            self.enc[text] = codeseq
            self.dec[codeseq] = text
            if prefix == "/":
                self.eos.append(codeseq)

    def encode(self, string, enforce_eos=True):
        """ Encode a string into a series of bytes."""

        # FIXME: Needs to append EOS if called for.
        codeseq = []
        i = 0
        raw = r"^\[\$[a-fA-F0-9]{2}\]"
        last = None
        while i < len(string):
            if re.match(raw, string[i:]):
                # Oops, raw byte listing.
                code = int(string[i+2:i+4], 16)
                codeseq.append(code)
                i += 5
            else:
                match, code = self.enc.item(string[i:])
                codeseq.extend(code)
                i += len(match)
            last = code
        if enforce_eos and last not in self.eos:
            codeseq.extend(self.eos[0])

        return bytes(codeseq), len(string)

    def decode(self, data, include_eos=True, stop_on_eos=True):
        """ Decode a series of bytes.

        Any unrecognized bytes will be rendered as hex codes.
        """
        text = ""
        i = 0
        # the python codec infrastructure passes decode a memoryview, not
        # bytes, which makes patricia-trie choke
        if isinstance(data, memoryview):
            data = bytes(data)
        while i < len(data):
            raw = "[${:02X}]".format(data[i])
            match, string = self.dec.item(data[i:], default=raw)
            if match is None:
                match = data[i:i+1]
            if include_eos or (match not in self.eos):
                text += string
            if stop_on_eos and (match in self.eos):
                i += len(match)
                break
            i += len(match)
        return text, i


tt_codecs = {}
def add_tt(name, f):
    tt = TextTable(name, f)
    # Arguments to pass to tt.decode for each codec.
    args = {"":       (True, True, False),
            "-std":   (True, True, False),
            "-clean": (False, True, True),
            "-raw":   (True, False, False)}

    for subcodec, (include_eos, stop_on_eos, enforce_eos) in args.items():
        # There has got to be a cleaner way to do this...
        decoder = functools.partial(tt.decode,
                                    include_eos=include_eos,
                                    stop_on_eos=stop_on_eos)
        encoder = functools.partial(tt.encode,
                                    enforce_eos=enforce_eos)
        fullname = name + subcodec
        codec = codecs.CodecInfo(
                name=fullname,
                encode=encoder,
                decode=decoder
                )
        codec.eos = tt.eos
        log.debug("Adding text codec: %s", fullname)
        tt_codecs[fullname] = codec
    return tt

def get_tt_codec(name):
    return tt_codecs.get(name, None)

codecs.register(get_tt_codec)
