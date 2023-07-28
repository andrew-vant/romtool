import codecs
import logging
from collections import ChainMap
from functools import partial
from dataclasses import dataclass, fields, asdict
from io import BytesIO
from abc import ABC, abstractmethod
from collections.abc import Mapping

from asteval import Interpreter

from .io import Unit, BitArrayView
from .util import HexInt, IndexInt, locate

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
        if key == 'root':
            return self.struct.view.root
        if key == 'parent':
            log.warning("offset reference to 'parent' in map; "
                        "I am not sure if its behavior is correct")
            return -self.struct.view.abs_start % 8
        if key in ('rom', 'file'):
            raise NotImplementedError
        if key in self.struct.fids:
            return getattr(self.struct, key)
        raise KeyError(f"name not in context: {key}")

    def __iter__(self):
        yield 'rom'
        yield 'root'
        yield from self.struct.fids

    def __len__(self):
        return len(iter(self))


class FieldExpr:
    """ A field property whose value may be variable

    This is mainly of use for field offsets and sizes that are defined by
    another field of the parent structure.
    """
    DYNAMIC = object()  # Sentinel static value since None may be valid

    def __init__(self, spec):
        if not spec:
            raise ValueError("empty fieldexpr spec")
        self.spec = spec

        # Eval of any kind can be dangerous, and I'd like third-party maps to
        # be safe-ish, so for now let's avoid any builtin stuff at all and see
        # if it's good enough.
        #
        # NOTE: Interpreter creation is *surprisingly* expensive, espcially the
        # default symtable creation. So skip the default creation and make the
        # interpreter only once. We'll set the actual symtable just before
        # using it.
        self.interpreter = Interpreter({}, minimal=True)

        # NOTE: eval itself is pretty expensive, and the vast majority of
        # these expressions are simple integers. Let's pre-calculate if
        # possible.
        try:
            self.value = int(spec, 0)
        except ValueError:
            self.value = self.DYNAMIC

    def __repr__(self):
        return f"{type(self)}('{self.spec}')"

    def __str__(self):
        return self.spec

    def eval(self, parent):
        if self.value is not self.DYNAMIC:
            return self.value
        self.interpreter.symtable = FieldContext(parent)
        result = self.interpreter.eval(self.spec)
        errs = self.interpreter.error
        if errs:
            msg = "error evaluating FieldExpr '{}': {}"
            for err in errs:
                log.error(msg.format(self.spec, err.msg))
            raise RomtoolError(msg.format(self.spec, err.msg))
        return result

@dataclass
class Field(ABC):
    """ Define a ROM object's type and location

    There's a lot of things needed to fully characterize "what something is,
    and where":

    - id       (python identifier; used as attribute name on structs)
    - name     (arbitrary string; used as dictionary key and table heading)
    - type     (could be a sub-struct or str or custom type (FF1 spell arg))
    - origin   ([parent], rom, file)
    - unit     (bits, bytes, kb)
    - offset   (0, 0xFF, other_field, other_field +0xFF? default to previous field's offset + length, or 0)
    - size     (8, 0xFF)
    - arg      (endian for bits, modifier for ints?)
    - display  (format spec (ints) or encoding (str), implement __format__ somewhere?)
    - ref      (int is an index of a table entry)
    - order    (output order)
    - comment  (e.g. meaning of bits (but pretty sure I should use substruct for bitfields?))
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

    def __post_init__(self):
        """ Perform sanity checks after construction """
        self.name = self.name or self.id
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
        return 'name' in (self.id.lower(), self.name.lower())

    @property
    def is_flag(self):
        return self.size.spec == '1' and self.unit == Unit.bits

    @property
    def is_ptr(self):
        return self.display == 'pointer'

    @property
    def is_unknown(self):
        return 'unknown' in self.name.lower()

    @property
    def is_slop(self):
        slop_names = ['padding', 'reserved']
        return self.name.lower() in slop_names

    @property
    def identifiers(self):
        return [self.id, self.name]

    def view(self, obj):
        """ Get the bitview corresponding to this field's data """
        # FIXME: Terrible. Mostly for cases where Tables need to read strings
        # that aren't part of a struct. Should read() take a view instead of an
        # object, and let __get__ handle cases where there is an actual parent?
        if isinstance(obj, BitArrayView):
            return obj
        # Get the parent view that this field is "relative to"
        context = (obj.view if not self.origin
                   else obj.view.root if self.origin == 'root'
                   else obj.root.data if self.origin == 'rom'
                   else obj.view.root.find(self.origin))
        offset = self.offset.eval(obj) * self.unit
        size = self.size.eval(obj) * self.unit
        end = offset + size
        return context[offset:end]

    def __get__(self, instance, owner=None):
        return self.read(instance, owner)

    def __set__(self, instance, value):
        old = self.__get__(instance)
        self.write(instance, value)
        new = self.__get__(instance)
        if new != old:
            log.debug("change: %s.%s %s -> %s", instance, self.id, old, new)

    def read(self, obj, objtype=None):
        """ Read from a structure field

        The default implementation assumes the field's `type` is a readable
        attribute of a bitview.
        """
        if obj is None:
            return self
        view = self.view(obj)
        assert len(view) == self.size.eval(obj) * self.unit
        return getattr(view, self.type)

    def write(self, obj, value):
        """ Write to a structure field

        The default implementation assigns to the bitview attribute named by
        self.type.
        """
        setattr(self.view(obj), self.type, value)

    def parse(self, string):
        """ Parse the string representation of this field's value type

        The resulting value is returned, for convenience.
        """
        raise NotImplementedError("don't know how to parse a %s", type(self))

    @classmethod
    def from_tsv_row(cls, row, extra_fieldtypes=None):
        cls = ChainMap(extra_fieldtypes or {}, DEFAULT_FIELDS)[row['type']]
        kwargs = {}
        convtbl = {int: partial(int, base=0),
                   Unit: Unit.__getitem__,
                   FieldExpr: FieldExpr,
                   str: str}
        for field in fields(cls):
            k = field.name
            v = row.get(k, None) or None  # ignore missing or empty values
            if v is not None:
                kwargs[k] = convtbl[field.type](v)
        return cls(**kwargs)

    def asdict(self):
        return {f.name: getattr(self, f.name) or '' for f in fields(self)}


class StringField(Field):
    """ Field for fixed-width strings """

    @property
    def codec(self):
        return codecs.lookup(self.display or 'ascii')

    def read(self, obj, objtype=None):
        if obj is None:
            return self
        return self.view(obj).bytes.decode(self.display).rstrip()

    def write(self, obj, value):
        """ Write a fixed-width string

        Strings longer than the expected width are rejected; shorter strings
        are padded with spaces. Before writing, the old value is decoded and
        compared to the new one, and the change is ignored if they match. This
        prevents spurious changes when there are multiple valid encodings for a
        string.
        """
        if value.rstrip() == self.read(obj).rstrip():
            return  # ignore no-ops
        # Pad fixed-length strings with spaces. I feel like there should be a
        # better way to do this.
        view = self.view(obj)
        content = BytesIO(self.codec.encode(' ')[0] * len(view.bytes))
        content.write(value.encode(self.display))
        content.seek(0)
        view.bytes = content.read()

    def parse(self, string):
        return string


class StringZField(StringField):
    """ Field for strings with a terminator """

    @property
    def codec(self):
        return codecs.lookup('ascii' if not self.display
                             else f'{self.display}_clean')

    def _decode(self, obj):
        """ Get the string and bytecount of the current value """
        # Evil way to figure out if we're using a default codec, like ascii, or
        # a texttable. The default codecs don't stop on nulls, but we probably
        # want to. FIXME: Awful, find a better way to do this.
        view = self.view(obj)
        b_old = (view.bytes if hasattr(self.codec.decode.__self__, 'eos')
                 else view.bytes.partition(b'\0')[0])
        s_old, bct_old = self.codec.decode(b_old)
        return s_old, bct_old

    def read(self, obj, objtype=None):
        if obj is None:
            return self
        return self._decode(obj)[0]

    def write(self, obj, value):
        """ Write a terminated string

        Before writing, the old value is decoded and compared to the new one,
        and the change is ignored if they match. This prevents spurious changes
        when there are multiple valid encodings for a string.

        Replacing a string with a longer string will usually cause problems,
        but some use cases call for it. Doing so is allowed, but emits a
        warning.
        """
        s_old, bct_old = self._decode(obj)
        if value == s_old:
            return
        b_new = self.codec.encode(value)[0]
        overrun = len(b_new) - bct_old
        if overrun > 0:
            log.warning(f"replacement string '{value}' overruns end of old "
                        f"string '{s_old}' by {overrun} bytes")
        else:
            log.debug(f"replacing string '{s_old}' (len {bct_old}) "
                      f"with '{value}' (len {len(b_new)})")
        view = self.view(obj)
        content = BytesIO(view.bytes)
        content.write(b_new)
        content.seek(0)
        view.bytes = content.read()


class IntField(Field):
    def _enum(self, obj):
        """ Get any relevant enum type """
        try:
            return obj.root.map.enums.get(self.display)
        except (KeyError, AttributeError):
            return None

    def read(self, obj, objtype=None, realtype=None):
        if obj is None:
            return self
        view = self.view(obj)
        i = getattr(view, (realtype or self.type)) + (self.arg or 0)
        if self.display in ('hex', 'pointer'):
            i = HexInt(i, len(view))
        if self._enum(obj):
            i = self._enum(obj)(i)
        if self.ref:
            for source in obj.root.entities, obj.root.tables:
                if self.ref in source:
                    i = IndexInt(source[self.ref], i)
                    break
            else:
                raise ValueError(f"bad cross-reference key: {self.ref}")
        return i

    def write(self, obj, value, realtype=None):
        if isinstance(value, str):
            if self._enum(obj):
                try:
                    value = self._enum(obj)[value]
                except KeyError:
                    value = int(value, 0)
            elif self.ref:
                # FIXME: break crossref resolution into a separate function.
                # Not sure if it should be part of the field or somewhere else.
                if not value:
                    log.debug(f"empty cross-ref for {self.name} ignored")
                    return
                for source in obj.root.entities, obj.root.tables:
                    if self.ref in source:
                        key = value
                        value = locate(source[self.ref], value)
                        if source[value].name == key:
                            return
                        break
                else:
                    raise MapError(f"bad cross-reference: {self.ref}")
            else:
                value = int(value, 0)
        view = self.view(obj)
        value -= (self.arg or 0)
        setattr(view, (realtype or self.type), value)

    def parse(self, string):
        parser = self._enum.parse if self._enum else partial(int, base=0)
        return parser(string)


class BytesField(Field):
    def parse(self, string):
        return bytes.fromhex(string)


class StructField(Field):
    def read(self, obj, objtype=None, realtype=None):
        if obj is None:
            return self
        view = self.view(obj)
        return obj.root.map.structs[realtype or self.type](view, obj)

    def write(self, obj, value, realtype=None):
        target = self.read(obj)
        if isinstance(value, str):
            target.parse(value)
        else:
            value.copy(target)

    def parse(self, string):
        raise NotImplementedError


class ObjectField(StructField):
    """ Dummy field, for when a field is needed but won't be used """


class BinField(Field):
    def parse(self, string):
        # libreoffice thinks it's hilarious to truncate 000011 to 11; pad as
        # necessary if possible.
        if isinstance(self.size, int):
            string = string.zfill(self.size * self.unit)
        return string


DEFAULT_FIELDS = {
    'bin': BinField,
    'object': ObjectField,
    'bytes': BytesField,
    'int': IntField,
    'uint': IntField,
    'uintbe': IntField,
    'uintle': IntField,
    'nbcdle': IntField,
    'nbcdbe': IntField,
    'str': StringField,
    'strz': StringZField,
    }
