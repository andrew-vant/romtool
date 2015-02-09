from patricia import trie

class TextTable(object):
    def __init__(self, filename):
        self.id = None
        self.enc = trie()
        self.dec = trie()
        self.eos = []

        with open(filename) as f:
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
                raise NotImplementedError("Table switching not yet implemented.")

            code, text = line.split("=", 1)
            codeseq = bytes.fromhex(code)
            self.enc[text] = codeseq
            self.dec[codeseq] = text
            if prefix == "/":
                self.eos.append(codeseq)

    def readstr(self, f, pos = None, include_eos = True, maxlen = 1000):
        """ Read and decode an eos-terminated string from a file.

            Keyword arguments:
            maxlen -- Fail if no eos encountered before this many bytes.
        """
        if pos is not None:
            f.seek(pos)
        data = f.read(maxlen)
        return self.decode(data, include_eos=include_eos)

    def encode(self, s):
        codeseq = []
        i = 0
        while i < len(s):
            match, code = self.enc.item(s[i:])
            codeseq.extend(code)
            i += len(match)
        return bytes(codeseq)

    def decode(self, data, include_eos = True, stop_on_eos = True):
        text = ""
        i = 0
        while i < len(data):
            match, s = self.dec.item(data[i:])
            if include_eos or match not in self.eos:
                text += s
            if stop_on_eos and match in self.eos:
                break
            i += len(match)
        return text
