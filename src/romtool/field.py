import builtins
import logging
from collections import ChainMap
from functools import partial
from dataclasses import dataclass, fields
from io import BytesIO
from abc import ABC
from collections.abc import Mapping

from asteval import Interpreter

from .io import Unit
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
            err = None
            for err in errs:
                log.error(msg.format(self.spec, err.msg))
            # We can log all errors but I don't have a great way to represent
            # them all in the raised exeption, so for now just use the last one
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
        return any((s.lower().startswith('name') for s in [self.id, self.name]))

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
        if instance is None:
            return self
        return self.read(instance)

    def __set__(self, instance, value):
        old = self.__get__(instance)
        self.write(instance, value)
        new = self.__get__(instance)
        if new != old:
            log.debug("change: %s.%s %s -> %s", instance, self.id, old, new)

    def read(self, obj):
        """ Read from a structure field

        The default implementation assumes the field's `type` is a readable
        attribute of a bitview.
        """
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

        Returns the resulting value.
        """
        raise NotImplementedError(f"don't know how to parse a {type(self)}")

    @staticmethod
    def from_tsv_row(row, extra_fieldtypes=None):
        try:
            cls = ChainMap(extra_fieldtypes or {}, DEFAULT_FIELDS)[row.get('type')]
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

    def asdict(self):
        return {f.name: getattr(self, f.name) or '' for f in fields(self)}


class StringField(Field):
    """ Field for fixed-width strings """

    def codec(self, obj):
        _codec = obj.root.map.ttables[self.display or 'ascii']
        if not _codec:
            raise LookupError(f"no such codec: {self.display}")
        return _codec

    def read(self, obj):
        view = self.view(obj)
        codec = self.codec(obj).std
        return codec.decode(view.bytes, 'bracketreplace')[0].rstrip()

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
        codec = self.codec(obj).std
        content = BytesIO(codec.encode(' ')[0] * len(view.bytes))
        content.write(codec.encode(value, 'bracketreplace')[0])
        content.seek(0)
        view.bytes = content.read()

    def parse(self, string):
        return string


class StringZField(StringField):
    """ Field for strings with a terminator """

    def _decode(self, obj):
        """ Get the string and bytecount of the current value """
        view = self.view(obj)
        codec = self.codec(obj).clean
        return codec.decode(view.bytes, 'bracketreplace')

    def read(self, obj):
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
        codec = self.codec(obj).clean
        s_old, bct_old = self._decode(obj)
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
        self.view(obj).write(b_new)


class IntField(Field):
    def _enum(self, obj):
        """ Get any relevant enum type """
        try:
            return obj.root.map.enums.get(self.display)
        except (KeyError, AttributeError):
            return None

    def read(self, obj, realtype=None):
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
                    log.debug("empty cross-ref for %s ignored", self.name)
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
        # FIXME: does not do the right thing for enum types. *Can't* do the
        # right thing with enum types with the current design, because
        # there's no way to look up the relevant map from here.
        return int(string, base=0)


class BytesField(Field):
    def parse(self, string):
        return bytes.fromhex(string)


class StructField(Field):
    def read(self, obj, realtype=None):
        view = self.view(obj)
        return obj.root.map.structs[realtype or self.type](view, obj)

    def write(self, obj, value, realtype=None):  # pylint: disable=unused-argument
        target = self.read(obj, realtype=realtype)
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
