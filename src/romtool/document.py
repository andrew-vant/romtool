import logging
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from functools import cache, partial
from itertools import chain
from operator import attrgetter
from pathlib import Path

import appdirs
import dominate
import jinja2
from dominate import tags
from dominate.tags import dd, dl, dt, p, tr, td, th
from markupsafe import Markup
from more_itertools import unique_everseen

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
    data = [item if isinstance(item, Mapping) else {"value": item}
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
                    value = row.get(col)
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
def tbl_structdef(cls, *args, **kwargs):
    """ Document a structure's fields in HTML.

    Returns an HTML figure with a table inside it. Any field-specific notes
    are placed in the figure caption. """
    notes = {field.name: field.comment for field in cls.fields
             if field.comment}
    specs = [dict(field=field.name, **asdict(field)) for field in cls.fields]
    for spec in specs:
        # Remove keys we don't want in the headers
        for key in 'id name display order comment'.split():
            spec.pop(key)
    tableize(specs, identifiers='id field')
    tbl_notes(notes)


@tags.figure(cls="table")
def tbl_bitfield(cls, *args, **kwargs):
    """ Document a bitfield structure. """

    def by_offset(field):
        """ Get the offset of a bit, for sorting. """
        return field.offset.value

    notes = {field.name: field.comment for field in cls.fields
             if field.comment}
    specs = [{"bit": field.offset,
              "label": field.display,
              "description": field.name}
             for field in cls.fields]
    tableize(specs, None, identifiers=None)
    tbl_notes(notes)

def tbl_table_dump(table):
    return tableize(dict(offset=offset, value=obj)
                    for offset, obj
                    in table.with_offsets())




def finalize(obj):
    """ Jinja object finalizer. """
    def issubcls(obj, _type):
        """ issubclass wrapper that plays nice with non-class inputs """
        return isinstance(obj, type) and issubclass(obj, _type)
    # The Markup() here stops Jinja from escaping the output. The safe filter
    # doesn't work because it interferes with finalize.
    return (Markup(tbl_bitfield(obj)) if issubcls(obj, BitField)
            else Markup(tbl_structdef(obj)) if issubcls(obj, Structure)
            else Markup(tableize(obj)) if isinstance(obj, EntityList)
            else Markup(tbl_table_dump(obj)) if isinstance(obj, Table)
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
