""" Rom data structures

These objects form a layer over the raw rom, such that accessing them
automagically turns the bits and bytes into integers, strings, etc.
"""
import logging
import enum
from types import SimpleNamespace
from collections.abc import Mapping, Sequence
from collections import Counter
from itertools import chain, combinations

import yaml
from anytree import NodeMixin

from .primitives import uint_cls
from . import util


log = logging.getLogger(__name__)


class Structure(Mapping, NodeMixin):
    """ A structure in the ROM."""

    registry = {}
    labels = {}

    def __init__(self, view, parent=None):
        self.view = view
        self.parent = parent

    def _subview(self, field):
        # This ugliness is supposed to get us a bitarrayview of a single field
        # It's surprisingly difficult to handle int, str, and None values
        # concisely.
        context = (self.view if field.origin is None
                   else find(self.view.root, lambda n: n.name == field.origin))

        mapper = {str: lambda v: self[v] * field.unit,
                  int: lambda v: v * field.unit,
                  type(None): lambda v: v}

        offset = mapper[type(field.offset)](field.offset)
        size = mapper[type(field.size)](field.size)
        end = (size if not offset
               else offset + size if size
               else None)
        return context[offset:end]

    def _get(self, field):
        """ Plumbing behind getitem/getattr """
        subview = self._subview(field)
        if field.type in self.registry:
            return Structure.registry[field.type](subview, self)
        else:
            return field.read(subview)

    def _set(self, field, value):
        if field.type in self.registry:
            value.copy(self._get_struct(field))
        else:
            subview = self._subview(field)
            field.write(subview, value)

    def __getitem__(self, key):
        return self._get(self._fbnm(key))

    def __setitem__(self, key, value):
        self._set(self._fbnm(key), value)

    def __getattr__(self, key):
        return self._get(self._fbid(key))

    def __setattr__(self, key, value):
        # TODO: don't allow setting new attributes after definition is done.
        try:
            self._set(self._fbid(key), value)
        except AttributeError:
            super().__setattr__(key, value)

    @classmethod
    def _fbid(cls, fid):
        """ Get field by fid """
        # Consider functools.lru_cache if this is slow.
        try:
            return next(f for f in cls.fields if f.id == fid)
        except StopIteration as ex:
            raise AttributeError(f"No such field: {cls.__name__}.{fid}") from ex

    @classmethod
    def _fbnm(cls, fnm):
        """ Get field by name """
        try:
            return next(f for f in cls.fields if f.name == fnm)
        except StopIteration as ex:
            raise KeyError(f"No such field: {cls.__name__}[{fnm}])") from ex

    def __iter__(self):
        return (f.name for f in self.fields)

    def __len__(self):
        return len(self.fields)

    def _debug(self):
        return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                       for field in self.fields)

    def __format__(self, spec):
        outfmt, identifier = spec.split(":")
        if outfmt != 'y':
            raise ValueError("bad format string: {spec}")
        if identifier == 'i':
            return ''.join(f'{field.id}: {getattr(self, field.id)}\n'
                           for field in self.fields)
        elif identifier == 'n':
            return ''.join(f'{field.name}: {self[field.name]}\n'
                           for field in self.fields)
        else:
            raise ValueError("bad format string: {spec}")

    def __str__(self):
        return yaml.dump(dict(self))

    def __repr__(self):
        tpnm = type(self).__name__
        offset = str(util.HexInt(self.view.abs_start,
            len(self.view.root).bit_length()))
        out = f"{tpnm}@{offset}"
        if hasattr(self, 'name'):
            name = self.name[:16]
            if len(self.name) > 16:
                name += '..'
            out += f" ({name})"
        return f"<{out}>"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        name = cls.__name__
        if name in cls.registry:
            raise ValueError(f"duplicate definition of '{name}'")
        cls.registry[name] = cls

    @classmethod
    def define(cls, name, fields):
        """ Define a type of structure from a list of Fields

        The newly-defined type will be registered and returned.
        """
        fields = list(fields)
        fids = [f.id for f in fields]
        names = [f.name for f in fields]
        for identifier in chain(fids, names):
            if hasattr(cls, identifier):
                msg = f"{name}.{identifier} shadows a built-in attribute"
                raise ValueError(msg)

        for a, b in combinations(fields, 2):
            dupes = set(a.identifiers) & set(b.identifiers)
            if dupes:
                msg = f"Duplicate identifier(s) in {name} spec: {dupes}"
                raise ValueError(msg)

        bases = (cls,)
        attrs = {'fields': fields}
        return type(name, bases, attrs)

    def copy(self, other):
        """ Copy all attributes from one struct to another"""
        for k, v in self.items():
            if isinstance(v, Mapping):
                v.copy(other[k])
            else:
                other[k] = v


class BitField(Structure):
    def __str__(self):
        return ''.join(label.upper() if self[label] else label.lower()
                       for label in self.labels.keys())

    def parse(self, s):
        if len(s) != len(self):
            raise ValueError("String length must match bitfield length")
        for k, letter in zip(self, s):
            self[k] = letter.isupper()

class Table(Sequence):
    def __init__(self, view, typename, index):
        """ Create a Table

        view:   The underlying bitarray view
        index:  a list of offsets within the view
        cls:    The type of object contained in this table.
        """

        self.view = view
        self.index = index
        self.cls = cls

    def __getitem__(self, i):
        self.view.bitpos = self.index[i]
        return self.cls.from_view(self.view[i:])

    def __setitem__(self, i, v):
        self.view.bitpos = self.index[i]
        v.to_view(self.view)

    def __len__(self):
        return len(self.index)

    @staticmethod
    def make_index(offset, count, stride, scale=8):
        return [(offset + stride * i) * scale
                for i in range(count)]
