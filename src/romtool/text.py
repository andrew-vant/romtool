""" Implements ROM text tables.

The accepted format is defined in Nightcrawler's "Text Table Format" standard.

I would be *really* happy if I could implement this using python's built in
codec capabilities.
"""

import re
import codecs
import logging

from addict import Dict
from patricia import trie

from . import util

log = logging.getLogger(__name__)
tt_codecs = {}  # texttable codec registry


class TextTable(codecs.Codec):
    """ A ROM text table, used for decoding and encoding text strings.

    Provide a file object for input. Some options control encoding/decoding:

    force_eos: Encoding adds a string terminator if the input
                 doesn't include one.
    stop_on_eos: Decoding stops on encountering a string terminator.
    include_eos: Decoded strings include the [EOS] string literal if a
                 string terminator was encountered.
    """
    def __init__(self, stream, stop_on_eos=True,
                 force_eos=True, include_eos=False):
        self.id = None  # pylint: disable=invalid-name
        self.enc = trie()
        self.dec = trie()
        self.eos = []
        self.force_eos = force_eos
        self.stop_on_eos = stop_on_eos
        self.include_eos = include_eos

        # Skip blank lines when reading.
        lines = [line for line
                 in stream.read().split("\n")
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

    # pylint: disable-next=redefined-builtin
    def encode(self, input, errors='strict'):
        """ Stateless encoder for text tables

        If the error handler is set to 'bracketreplace', bracketed hex
        sequences will be interpreted as bytes.

        FIXME: Previous should maybe be done with a separate function? Unsure.
        """
        codeseq = []
        i = 0
        raw = r"^\[\$[a-fA-F0-9]{2}\]"
        last = None
        while i < len(input):
            if errors == 'bracketreplace' and re.match(raw, input[i:]):
                # Oops, raw byte listing.
                code = int(input[i+2:i+4], 16)
                codeseq.append(code)
                i += 5
            else:
                match, code = self.enc.item(input[i:])
                codeseq.extend(code)
                i += len(match)
            last = code
        if self.force_eos and last not in self.eos:
            codeseq.extend(self.eos[0])

        return bytes(codeseq), len(input)

    # pylint: disable-next=redefined-builtin
    def decode(self, input, errors='strict'):
        """ Stateless decoder for text tables """
        handle = codecs.lookup_error(errors)
        text = ""
        i = 0
        # the python codec infrastructure passes a memoryview, not
        # bytes, which makes patricia-trie choke
        if isinstance(input, memoryview):
            input = bytes(input)
        while i < len(input):
            try:
                match, string = self.dec.item(input[i:])
            except KeyError:
                if errors == 'stop':
                    return text, i+1
                err = UnicodeDecodeError('ttable',  input, i, i+1,
                                         'no valid encoding')
                string, i = handle(err)
                match = None
            else:
                i += len(match)
            if self.include_eos or (match not in self.eos):
                text += string
            if self.stop_on_eos and (match in self.eos):
                break
        return text, i

    @classmethod
    def std(cls, stream):
        """ A TextTable with options matching the Nightcrawler quasi-standard

        Stops on EOS bytes and includes [EOS] markers when decoding. At time of
        writing, these are also the defaults.
        """
        return cls(stream, stop_on_eos=True,
                   include_eos=True, force_eos=False)

    @classmethod
    def clean(cls, stream):
        """ A TextTable with cleaner decoding output

        Omits [EOS] markers when decoding and adds them back when encoding.
        """
        return cls(stream, stop_on_eos=True,
                   include_eos=False, force_eos=True)

    @classmethod
    def raw(cls, stream):
        """ A TextTable that ignores EOS markers when decoding

        Useful when looking for strings in mixed data.
        """
        return cls(stream, stop_on_eos=False,
                   include_eos=True, force_eos=False)

    @classmethod
    def variants(cls, stream):
        """ Yield all texttable codec variants as variant-codec pairs """
        loaders = {"clean": TextTable.clean,
                   "std":   TextTable.std,
                   "raw":   TextTable.raw}
        variants = Dict()
        for variant, loader in loaders.items():
            stream.seek(0)
            variants[variant] = loader(stream)
        return variants

    @classmethod
    def from_path(cls, path, loader=None):
        loader = loader or cls.variants
        with open(path) as f:
            return loader(f)



def bracketreplace_errors(ex):
    """ Bracket invalid characters by nightcrawler's quasi-standard """
    bad = ex.object[ex.start:ex.end]
    replacement = ''.join(f'[${byte:02X}]' for byte in bad)
    return (replacement, ex.end)


def stop_errors(ex):
    """ Treat invalid characters as end-of-string.

    Useful for string searching when the encoding doesn't have an EOS marker.
    I haven't figured out how to do this from an error handler yet.
    """
    raise NotImplementedError


def add_tt(name, stream):
    """ Register all variations of a file's texttable """
    subs = {f"{name}":       TextTable.std,
            f"{name}_std":   TextTable.std,
            f"{name}_clean": TextTable.clean,
            f"{name}_raw":   TextTable.raw}
    for subname, factory in subs.items():
        stream.seek(0)
        tt = factory(stream)  # pylint: disable=invalid-name
        codec = codecs.CodecInfo(tt.encode, tt.decode, name=subname)
        log.debug("Adding text codec: %s", subname)
        tt_codecs[subname] = codec
    return tt


def get_tt_codec(name):
    """ Look up a TextTable codec """
    return tt_codecs.get(name, None)


def clear_tt_codecs():
    """ Clear any registered texttables """
    codecs.unregister(get_tt_codec)
    tt_codecs.clear()
    codecs.register(get_tt_codec)


tt_codecs.update(util.load_builtins('texttables', '.tbl', TextTable.from_path))
codecs.register(get_tt_codec)
codecs.register_error('bracketreplace', bracketreplace_errors)
codecs.register_error('stop', stop_errors)
