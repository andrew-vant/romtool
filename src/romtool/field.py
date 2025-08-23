""" Descriptors for low-level data fields.

These are typically used as attributes on structure types.
"""
import builtins
import logging
from abc import ABC
from collections.abc import Mapping
from collections import ChainMap
from dataclasses import dataclass, fields
from functools import cached_property, partial
from io import BytesIO

from asteval import Interpreter

from .io import Unit
from .text import get_tt_codec
from .util import HexInt, IndexInt, locate, throw

from .exceptions import RomtoolError, MapError

log = logging.getLogger(__name__)


class FieldContext(Mapping):
    """ A dict-like context intended to be passed to asteval

    The following names are available when evaluating:

    * `root` refers to the root file view
    * `rom` refers to the rom object
    * all field IDs of the structure being evaluated are available, and will
      read the value of that field.
    * TODO: table names from the ROM, so you don't need rom.table
    * TODO: the index of the struct within its table. Useful for
      cross-references.
    """
    def __init__(self, struct):
        self.struct = struct

    def __getitem__(self, key):
        if key == 'parent':
            log.warning("offset reference to 'parent' in map; "
                        "I am not sure if its behavior is correct")
        return (
            self.struct.view.root if key == 'root'
            else self.struct.root if key == 'rom'
            else -self.struct.view.abs_start % 8 if key == 'parent'
            else getattr(self.struct, key) if key in self.struct.attrs()
            else getattr(builtins, key) if hasattr(builtins, key)
            else throw(KeyError(f"name not in context: {key}"))
        )

    def __iter__(self):
        yield from ['root', 'rom', 'parent']
        yield from self.struct.attrs()

    def __len__(self):
        return len(iter(self))


class FieldExpr:
    """ A field property whose value may be variable

    This is mainly of use for field offsets and sizes that are defined by
    another field of the parent structure. If the expression has a fixed
    value then it is precalculated to avoid repeated (expensive) evaluation.
    """
    # FIXME: Maybe this should be folded into Field, or made more generic.

    DYNAMIC = object()  # Sentinel static value since None may be valid

    def __init__(self, spec):
        if not spec:
            raise ValueError("empty fieldexpr spec")
        self.spec = spec

    @cached_property
    def interpreter(self):
        """ The interpreter used to evaluate this field.

        Interpreter creation is *surprisingly* expensive, especially the
        default symtable creation, so this creates the interpreter only on
        first use, with no symtable. Set the actual symtable just before
        evaluation.
        """
        # This is a property rather than an attribute to avoid breaking
        # asdict() on parent objects -- asdict relies on objects being
        # pickleable, and interpreters aren't.
        return Interpreter({}, minimal=True)

    @cached_property
    def value(self):
        """ Static value of this expression, if possible.

        Eval is pretty expensive, and the vast majority of expressions are
        simple integers. In such cases it can be evaled once and never again.
        """
        try:
            return int(self.spec, 0)
        except ValueError:
            return self.DYNAMIC

    def __repr__(self):
        return f"{type(self)}('{self.spec}')"

    def __str__(self):
        return self.spec

    def eval(self, parent):
        """ Evaluate the field against a given parent object. """
        if self.value is not self.DYNAMIC:
            return self.value
        self.interpreter.symtable = FieldContext(parent)
        result = self.interpreter.eval(self.spec)
        errs = self.interpreter.error
        if errs:
            msg = "error evaluating FieldExpr '{}': {}"
            err = None
            for err in errs:
                log.error(msg.format(self.spec, err.msg))
            # We can log all errors but I don't have a great way to represent
            # them all in the raised exeption, so for now just use the last one
            raise RomtoolError(msg.format(self.spec, err.msg))
        return result


@dataclass
class Field(ABC):  # pylint: disable=too-many-instance-attributes
    """ Define a ROM object's type and location

    There's a lot of things needed to fully characterize "what something is,
    and where":

    - id       (python identifier; used as attribute name on structs)
    - name     (arbitrary string; used as dictionary key and table heading)
    - type     (could be a sub-struct or str or custom type (FF1 spell arg))
    - origin   ([parent], rom, file)
    - unit     (unit for offset/size; e.g. bits, bytes, kb)
    - offset   (offset from origin in units, or FieldExpr producing same)
    - size     (field size in units)
    - arg      (endian for bits, modifier for ints?)
    - display  (encoding (of strings) or __format__ spec (most other types))
    - ref      (int is an index of a table entry)
    - order    (output order)
    - comment  (additional notes)

    Subclasses must provide read(), write(), and parse() methods. See below
    for their expected behavior.
    """

    id: str
    name: str = None
    type: str = 'uint'
    origin: str = None
    unit: Unit = Unit.bytes
    offset: FieldExpr = None
    size: FieldExpr = '1'
    arg: int = None
    ref: str = None
    display: str = None
    order: int = 0
    comment: str = ''

    NOOP = object()  # may be returned from parse() or passed to write()

    def __set_name__(self, owner, name):
        self.desc = f"{owner.__name__}.{name}"

    def __str__(self):
        return getattr(self, 'desc') or repr(self)

    def __post_init__(self):
        """ Perform sanity checks after construction """
        self.name = self.name or self.id
        self.desc = f"<unknown>.{self.name}"
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None and not isinstance(value, field.type):
                raise ValueError(f'Expected {field.name} to be {field.type}, '
                                 f'got {type(value)}')
        if self.offset is None:
            msg = f"'{self.id}' field missing required offset property"
            raise RomtoolError(msg)

    def _sort_for_readability(self):
        """ Get an ordering key for this field

        It's often useful to order fields for readability rather than the
        typical (in specs) offset order. This orders name fields first, pushes
        opaque or unknown fields towards the end, and otherwise orders
        according to the sort order given in the spec.

        Sorting an iterable of fields directly will use this key.
        """
        return (
                self.id != 'id',
                not self.is_name,
                self.is_slop,
                self.is_ptr,
                self.is_unknown,
                self.is_flag,
                self.order or 0,
               )

    def __lt__(self, other):
        return self._sort_for_readability() < other._sort_for_readability()

    @property
    def is_name(self):
        """ Check if the field is the name of the parent object. """
        return (not self.is_ptr
                and any((s.lower().startswith('name')
                         for s in [self.id, self.name])))

    @property
    def is_flag(self):
        """ Check if the field is a boolean flag. """
        return self.size.spec == '1' and self.unit == Unit.bits

    @property
    def is_ptr(self):
        """ Check if the field contains a pointer. """
        return self.display == 'pointer'

    @property
    def is_unknown(self):
        """ Check if the field's purpose is unknown. """
        return 'unknown' in self.name.lower()

    @property
    def is_slop(self):
        """ Check if the field is meaningless padding or similar. """
        slop_names = ['padding', 'reserved']
        return self.name.lower() in slop_names

    @property
    def identifiers(self):
        """ Get valid identifiers for this field (e.g. id and name). """
        return [self.id, self.name]

    def view(self, obj):
        """ Get the bitview corresponding to this field's data """
        # Get the parent view that this field is "relative to"
        context = (obj.view if not self.origin
                   else obj.view.root if self.origin == 'root'
                   else obj.root.data if self.origin == 'rom'
                   else obj.view.root.find(self.origin))
        # Now get the slice actually corresponding to this object
        offset = self.offset.eval(obj) * self.unit
        size = self.size.eval(obj) * self.unit
        end = offset + size
        return context[offset:end]

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self.read(instance, self.view(instance))

    def __set__(self, instance, value):
        if isinstance(value, str):
            value = self.parse(instance, value)
        if value is self.NOOP:
            return
        view = self.view(instance)

        # Can it ever be the case that writing and re-reading returns
        # something different than the original value? Yes, at the moment
        # StructField does this because its actual parsing happens in
        # write(), not parse(). I really ought to fix that.
        old = self.read(instance, view)
        if value == old:  # order here might matter for some types?
            return
        log.debug("about to write")
        self.write(instance, view, value)
        new = self.read(instance, view)
        if new != old:
            assert not self.id.startswith("drp")
            log.debug("change: %s.%s %s -> %s", instance, self.id, old, new)

    def read(self, obj, view):
        """ Read this field from a bitview.

        The default implementation assumes the field's type is a readable
        attribute of the bitview.
        """
        assert len(view) == self.size.eval(obj) * self.unit
        return getattr(view, self.type)

    def write(self, obj, view, value):  # pylint: disable=unused-argument
        """ Write to a structure field

        The default implementation assigns to the bitview attribute named by
        self.type.
        """
        setattr(view, self.type, value)

    def parse(self, obj, string):
        """ Parse the string representation of this field's value type

        The input value should be one produced by `str(self.read())`. Returns
        a value type that can be passed on to .write(), or Field.NOOP to
        indicate "make no change."
        
        The default implementation returns the string unchanged.
        """
        return string

    @staticmethod
    def from_tsv_row(row, extra_fieldtypes=None):
        """ Define a field from a tsv row (e.g. from a struct def file). """
        extra_fieldtypes = extra_fieldtypes or {}
        try:
            cls = ChainMap(extra_fieldtypes, DEFAULT_FIELDS)[row.get('type')]
        except KeyError as ex:
            raise MapError(f"unknown field type: {ex}") from ex
        kwargs = {}
        convtbl = {int: partial(int, base=0),
                   Unit: Unit.__getitem__,
                   FieldExpr: FieldExpr,
                   str: str}
        # Keep in mind that here we're iterating over the dataclass-fields of
        # the field type object. As if this wasn't confusing enough.
        for field in fields(cls):
            k = field.name
            v = row.get(k)
            if not v:  # ignore missing or empty values
                continue
            try:
                kwargs[k] = convtbl[field.type](v)
            except (KeyError, ValueError) as ex:
                fid = row.get('id') or None
                raise MapError(f'invalid {k}: {ex}', fid) from ex
        return cls(**kwargs)


class StringField(Field):
    """ String field. """

    def codec(self, obj):
        """ Get the character encoding for this field. """
        # If the current rom doesn't have a map, look at the built-in codecs
        # instead. This may happen e.g. when trying to print SNES header data.
        if not hasattr(obj.root, 'map'):
            return get_tt_codec(self.display or 'ascii')
        _codec = obj.root.map.ttables[self.display or 'ascii']
        if not _codec:
            raise LookupError(f"no such codec: {self.display}")
        return _codec

    def read(self, obj, view):
        codec = self.codec(obj).std
        return codec.decode(view.bytes, 'bracketreplace')[0].rstrip()

    def write(self, obj, view, value):
        """ Write a fixed-width string.

        Strings longer than the expected width are rejected; shorter strings
        are padded with spaces. Before writing, the old value is decoded and
        compared to the new one, and the change is ignored if they match. This
        prevents spurious changes when there are multiple valid encodings for a
        string.
        """
        # The no-op check needs to be somewhat fuzzy; we don't want
        # spurious "changes" to be introduced by e.g. different valid
        # encodings of the same string, or invisible whitespace differences
        # that could be introduced by external tools.
        if value.rstrip() == self.read(obj, view).rstrip():
            return
        # Pad fixed-length strings with spaces. I feel like there should be a
        # better way to do this.
        codec = self.codec(obj).std
        encoded = codec.encode(value, 'bracketreplace')[0]
        if len(encoded) > view.ct_bytes:
            raise ValueError(f"{value!r} won't fit in {self} "
                             f"{len(encoded)} bytes > {view.ct_bytes}")
        content = BytesIO(codec.encode(' ')[0] * view.ct_bytes)
        content.write(encoded)
        view.bytes = content.getvalue()

    def parse(self, obj, string):
        return string


class StringZField(StringField):
    """ Terminated-string field. """

    def _decode(self, obj, view):
        """ Get the string and bytecount of the current value """
        # Helper to avoid duplicating this in read/write
        codec = self.codec(obj).clean
        return codec.decode(view.bytes, 'bracketreplace')

    def read(self, obj, view):
        """ Read a terminated string. """
        return self._decode(obj, view)[0]

    def write(self, obj, view, value):
        """ Write a terminated string.

        Replacing a string with a longer string emits a warning. No-op
        changes are ignored as per StringField.write().
        """
        codec = self.codec(obj).clean
        s_old, bct_old = self._decode(obj, view)
        if value == s_old:
            return
        b_new = codec.encode(value, 'bracketreplace')[0]
        overrun = len(b_new) - bct_old
        if overrun > 0:
            log.warning("replacement string '%s' overruns end of old string "
                        "'%s' by %s bytes (%s > %s)",
                        value, s_old, overrun, len(b_new), bct_old)
        else:
            log.debug("replacing string '%s' (len %s) with '%s' (len %s)",
                      s_old, bct_old, value, len(b_new))
        view.write(b_new)


class IntField(Field):
    """ Integral field.

    The field's `arg` value is added on read and subtracted on write. This
    is intended mostly to support crossreferences that index items starting
    from one (with 0 indicating None).
    """

    def _enum(self, obj):
        """ Get the enum type, if any. """
        # FIXME: figure out how to cache this?
        try:
            return obj.root.map.enums.get(self.display)
        except (KeyError, AttributeError) as ex:
            log.debug(ex)
            return None

    def _xref(self, obj):
        """ Get cross-reference target, if any. """
        if not self.ref:
            return None
        # ChainMap doesn't play nice with addict.Dict, or I'd use it here
        for target in obj.root.entities, obj.root.tables:
            if self.ref in target:
                return target[self.ref]
        raise MapError(f"bad cross-reference in {self}: {self.ref}")

    def read(self, obj, view):
        i = getattr(view, self.type) + (self.arg or 0)
        enum = self._enum(obj)
        return (enum(i) if enum
                else IndexInt(self._xref(obj), i) if self.ref
                else HexInt(i, len(view)) if self.display in ('hex', 'pointer')
                else i)

    def write(self, obj, view, value):
        value -= (self.arg or 0)
        setattr(view, self.type, value)

    def parse(self, obj, string):
        enum = self._enum(obj)
        xref = self._xref(obj)
        # FIXME: treats empty xrefs as NOOPs. This is probably not the right
        # behavior, but not doing so causes spurious changes when the target
        # table contains multiple unnamed items, as happens in one of the
        # stock maps. Disambiguating crossrefs when dumping/building may be
        # problematic in general.
        return (enum[string] if enum
                else self.NOOP if xref and not string
                else locate(xref, string) if xref
                else self._parse_xref(obj, string) if xref
                else int(string, 0))


class StructField(Field):
    """ Field containing a nested structure. """
    def read(self, obj, view):
        return obj.root.map.structs[self.type](view, obj)

    def write(self, obj, view, value):  # pylint: disable=unused-argument
        target = self.read(obj, view)
        if isinstance(value, str):
            target.parse(value)
        else:
            value.copy(target)

    def parse(self, obj, string):
        # FIXME: not sure how to handle this appropriately, you can't parse
        # a string into a value-type here. Maybe return a dict and have
        # write() do update instead of target.parse?
        return string


class ObjectField(StructField):
    """ Dummy field, for when a field is needed but won't be used """


DEFAULT_FIELDS = {
    'bin': Field,
    'object': ObjectField,
    'bytes': Field,
    'int': IntField,
    'uint': IntField,
    'uintbe': IntField,
    'uintle': IntField,
    'nbcdle': IntField,
    'nbcdbe': IntField,
    'str': StringField,
    'strz': StringZField,
    }
