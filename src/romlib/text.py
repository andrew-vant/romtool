""" Implements ROM text tables.

The accepted format is defined in Nightcrawler's "Text Table Format" standard.

I would be *really* happy if I could implement this using python's built in
codec capabilities.
"""

import re

from patricia import trie


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

    def readstr(self, f, pos=None, include_eos=True, maxlen=1000):
        """ Read and decode an eos-terminated string from a file.

            Keyword arguments:
            maxlen -- Fail if no eos encountered before this many bytes.
        """
        if pos is not None:
            f.seek(pos)
        data = f.read(maxlen)
        return self.decode(data, include_eos, True)

    def readstr_bs(self, bs, pos=None, include_eos=True, maxlen=1024):
        """ Read and decode an eos-terminated string from a bitstring.

        Note that maxlen is *bytes*, not bits.
        """
        if pos is None:
            pos = bs.pos
        data = bs[pos:pos+maxlen]
        return self.decode(data.bytes, include_eos, True)

    def encode(self, string):
        """ Encode a string into a series of bytes."""
        codeseq = []
        i = 0
        raw = r"^\[\$[a-fA-F0-9]{2}\]"
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
        return bytes(codeseq)

    def decode(self, data, include_eos=True, stop_on_eos=True):
        """ Decode a series of bytes.

        Any unrecognized bytes will be rendered as hex codes.
        """
        text = ""
        i = 0
        while i < len(data):
            raw = "[${:02X}]".format(data[i])
            match, string = self.dec.item(data[i:], default=raw)
            if match is None:
                match = data[i:i+1]
            if include_eos or match not in self.eos:
                text += string
            if stop_on_eos and match in self.eos:
                break
            i += len(match)
        return text
