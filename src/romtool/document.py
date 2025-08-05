""" Rom documentation generation.

A combination of jinja, markdown, and dominate is used to generate the docs.
This is annoyingly complicated, especially when rendering data tables.
"""

import logging
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from functools import cache, partial
from itertools import chain
from pathlib import Path

import appdirs
import jinja2
from dominate import tags
from dominate.tags import a, dd, dl, dt, p, tr, td, th
from markdown import markdown, Markdown
from markupsafe import Markup
from more_itertools import unique_everseen

from .rom import Rom
from .structures import BitField, EntityList, Structure, Table
from .util import safe_iter, TSVReader

ichain = chain.from_iterable  # convenience alias
log = logging.getLogger(__name__)


def table_cols(dicts):
    """ Get a list of table columns for an iterable of dicts.

    Keys are emitted in order of appearance. Columns that would be empty are
    omitted.
    """
    # I don't see a way out of iterating twice
    dicts = list(dicts)
    keys = unique_everseen(ichain(d.keys() for d in dicts))
    return [k for k in keys if any(row.get(k) for row in dicts)]


def denonify(obj, replacement=''):
    """ Replace None with the empty string (or something else). """
    return replacement if obj is None else obj


@tags.table(cls="scroll")
def tableize(data, numbered='#', identifiers='id name'):
    """ Build an html table from a list of dicts.

    The key order of the first dict is used for the column order. Columns
    that would be empty are omitted. If `numbered` is a string, it is the
    heading for a prepended column numbering the rows.

    An iterable or space-separated string of identifier-keys will have the
    'identifier' class applied to them.
    """
    identifiers = (identifiers.split()
                   if isinstance(identifiers, str)
                   else list(identifiers or []))
    data = [item if isinstance(item, Mapping)
            else asdict(item) if is_dataclass(item)
            else {"value": item}
            for item in data]
    columns = table_cols(data)
    with tags.thead():
        if numbered is not None:
            th(numbered.title(), scope='col', cls='identifier')
        for col in columns:
            th(col.title(), scope='col',
               cls=col.lower() in identifiers and f'identifier {col}')
    with tags.tbody():
        for i, row in enumerate(data):
            with tr():
                if numbered is not None:
                    th(i, scope='row', cls='identifier')
                for col in columns:
                    td(str(denonify(row.get(col))),
                       cls=col.lower() in identifiers and f'identifier {col}')

@tags.figcaption()
def tbl_notes(notes):
    """ Create a table caption for entry notes. """
    if not notes:
        return
    p("Notes:")
    with dl(cls="tablenotes"):
        for name, note in notes.items():
            dt(name)
            dd(note)


@tags.figure(cls="table")
def tbl_structdef(cls):
    """ Document a structure's fields in HTML.

    Returns an HTML figure with a table inside it. Any field-specific notes
    are placed in the figure caption. """
    notes = {field.name: field.comment for field in cls.fields
             if field.comment}
    specs = [{'field': field.name, **asdict(field)} for field in cls.fields]
    for spec in specs:
        # Remove keys we don't want in the headers
        for key in 'name display order comment'.split():
            spec.pop(key)
    tableize(specs, identifiers='id field')
    tbl_notes(notes)


@tags.figure(cls="table")
def tbl_bitfield(cls):
    """ Document a bitfield structure. """

    notes = {field.name: field.comment for field in cls.fields
             if field.comment}
    specs = [{"bit": field.offset,
              "label": field.display,
              "description": field.name}
             for field in cls.fields]
    tableize(specs, None, identifiers=None)
    tbl_notes(notes)


def tbl_table_dump(table):
    """ Document the items in a ROM table. """

    def mkdict(offset, obj):
        """ Create instance dicts to send to tableize. """
        d = {'offset': offset}
        d.update(obj if isinstance(obj, Mapping)
                 else {'value': obj})
        return d

    return tableize(mkdict(offset, obj)
                    for offset, obj
                    in table.with_offsets())


@tags.figure(cls="table")
def tbl_entity_dump(table):
    """ Document the items in an EntityList. """
    tableize(table)
    with tags.figcaption():
        a("(as tsv)", cls="dump", href=f"{table.name}.tsv")


@tags.figure(cls="table")
def tbl_rom_toplevel(rom):
    """ Document the top-level list of ROM tables. """
    def index(table):
        """ Concisely describe the table index """
        if not isinstance(table._index, Table):
            return None
        spec = table._index.spec
        tp = spec.type
        ct = spec.count
        os = spec.offset
        sz = spec.stride
        return f'{tp}({sz})*{ct}@{os}'

    def sortkey(table):
        """ Sort key for tables. """
        return (table in rom.indexes,
                not table.spec.set,
                table.spec.set or '',
                table.name or '')

    # This is irritatingly explicit just to pick out/rename some fields.
    tables = [table for table in rom.tables.values()
              if table not in rom.indexes]

    entries = ({'name':   table.spec.name,
                'group':  table.spec.set,
                'type':   table.spec.type,
                'offset': table.spec.offset,
                'count':  table.spec.count,
                'stride': table.spec.stride,
                'index':  index(table)}
               for table in sorted(tables, key=sortkey))

    notes = {table.name: table.spec.comment
             for table in tables
             if table.spec.comment}
    tableize(entries, None, None)
    tbl_notes(notes)

def issubcls(obj, _type):
    """ issubclass wrapper that plays nice with non-class inputs """
    return isinstance(obj, type) and issubclass(obj, _type)

def finalize(obj):
    """ Jinja finalizer hook. """
    # The Markup() here stops Jinja from escaping the output. The safe filter
    # doesn't work because it interferes with finalize.
    return (Markup(tbl_bitfield(obj)) if issubcls(obj, BitField)
            else Markup(tbl_structdef(obj)) if issubcls(obj, Structure)
            else Markup(tbl_entity_dump(obj)) if isinstance(obj, EntityList)
            else Markup(tbl_table_dump(obj)) if isinstance(obj, Table)
            else Markup(tbl_rom_toplevel(obj)) if isinstance(obj, Rom)
            else '' if obj is None
            else obj)


@cache
def jinja_env():
    """ Return the jinja environment used for doc generation. """
    # Filters to add to the environment

    def getname(obj):
        return obj.__name__ if isinstance(obj, type) else obj.name

    user_templates = Path(appdirs.user_data_dir('romtool'), 'templates')
    escape_formats = ["html", "htm", "xml", "jinja"]  # Is this really needed?
    tpl_loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(user_templates),
        jinja2.PackageLoader('romtool'),
        ])
    env = jinja2.Environment(
            loader=tpl_loader,
            extensions=['jinja2.ext.do'],
            finalize=finalize,
            autoescape=jinja2.select_autoescape(escape_formats)
            )
    env.filters["safe_iter"] = safe_iter
    env.filters["asdict"] = asdict
    env.filters["name"] = getname
    env.filters["tableize"] = tableize
    env.filters["markdown"] = partial(markdown, extensions=['extra', 'toc'])
    return env


def tsv2html(infile, caption=None):
    """ Convert a tsv file to html.

    At present this is done with a jinja template. Probably it should
    actually be done with bs4 or something.
    """
    rows = list(TSVReader(infile))
    columns = [k for k in rows[0]
               if any(r[k].strip() for r in rows)]
    log.info("converting tsv: %s", caption)
    template = jinja_env().get_template('tsv2html.html')
    out = template.render(
            caption=caption,
            headers=columns,
            rows=({c: r[c] for c in columns} for r in rows),
            )
    return out


def jrender(_template, **context):
    """ Look up a jinja template and render it with context.

    Mostly this removes the need for the caller to think about jinja
    environment details.
    """
    return jinja_env().get_template(_template).render(**context)


def document(rom):
    """ Generate documentation for a ROM. """
    md = Markdown(extensions=['extra', 'toc'],
                  extension_configs={'toc': {
                      'toc_depth': '2-6',
                      }})
    content = md.convert(jrender('monolithic.md', rom=rom))
    return jrender('monolithic.html',
                   rom=rom,
                   content=content,
                   toc=md.toc)  # pylint: disable=no-member # added by extension
