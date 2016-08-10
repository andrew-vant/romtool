class Index(object):
    def __init__(self, spec):
        self.offset = int(spec['offset'], 0)
        self.stride = int(spec['stride'], 0)
        self.length = int(spec['length'], 0)

    def indices(self, bs):
        for i in range(self.length):
            yield self.stride * i + self.offset

class Array(object):
    def __init__(self, name, struct, index):
        """
        Index must be an object with a .indices() method that returns an
        iterable of integers, representing the start of each item in this
        array. The method must take one argument, which must accept either a
        bitstring or a file object; it need not actually use either, and if
        it reads them, it must reset their read position afterward.

        In practice this will either be an Index object (for fixed arrays) or
        another Array object (for indexed arrays).
        """
        self.name = name
        self.index = index
        self.struct = struct
        if self.index == self:
            msg = "Array '{}' tried to use itself as an index"
            raise ValueError(msg, name)
        self._indices = None

    def read(self, rom):
        bs = util.bsify(rom)
        logging.info("Reading ROM array: %s", self.name)
        indexer = self.struct.indexer
        if indexer:
            self._indices = []
        for offset in self.index.indices():
            bs.pos = offset * 8
            struct = self.struct(bs)
            if indexer:
                self._indices.append(struct[indexer.id])
            yield struct

    def indices(self, rom):
        if self._indices is None:
            # FIXME: What type of exception should this really be?
            msg = "Tried to index on array '{}' before first use"
            raise Exception(msg, self.name)
        return iter(self._indices)

    def load(self, dicts):
        """ Deserialize this array from an iterable of dicts."""
        # There should really be a way to factor the index-caching stuff out
        # from this function and .read()
        indexer = self.struct.indexer
        if indexer:
            self._indices = []
        sorter = lambda d: util.intify(d.get('_idx_', None))
        for dct in sorted(dicts, sorter):
            struct = self.struct(dct)
            if indexer:
                self._indices.append(struct[indexer.id])
            yield struct
