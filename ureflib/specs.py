import logging
import csv
from collections import namedtuple, OrderedDict

class SpecException(Exception):
    pass


class SpecFieldMismatch(SpecException):
    def __init__(self, message, required, provided):
        super().__init__(message)
        self.message = message
        self.required = required
        self.provided = provided
    def __str__(self):
        reqstr = "Fields required: {}".format(self.required)
        provstr = "Fields provided: {}".format(self.provided)
        return "\n".join(message, reqstr, provstr)


def load_tables(filename):
    """ Load a list of tables present in a ROM. """
    with open(filename, "rb") as f:
        return list(TableReader(f))


class OrderedDictReader(csv.DictReader):
    """ Read a csv file as a list of ordered dictionaries.

    This has one additional option over DictReader, "orderfunc", which specifies
    an sorting key over a dictionary's items. If it is not provided, the dictionary
    items will be sorted in the same order as the csv's columns. This makes it
    possible to re-write the same file without interfering with its column
    order.

    Note that a corresponding OrderedDictWriter is not needed; supply an ordered
    dictionary's .keys() as the fieldnames for a regular DictWriter.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orderfunc = kwargs.get("orderfunc",
                                     lambda t: self.fieldnames.index(t[0]))
    def __next__(self):
        d = super().__next__()
        return OrderedDict(sorted(d.items(), key=self._orderfunc))


class SpecReader(OrderedDictReader):

    def __init__(self, *args, requiredfields=[], **kwargs):
        super().__init__(*args, **kwargs)
        self.requiredfields = requiredfields

    def __next__(self):
        spec = super().__next__()
        if not all(field in spec for field in self.requiredfields):
            raise SpecFieldMismatch(
                "Spec appears to be missing fields.",
                self.requiredfields,
                spec.keys())
        return spec


class TableReader(SpecReader):

    tablefields = "name", "spec", "entries", "entrysize", "offset", "comment"
    tableentryfields = "fid", "label", "offset", "size", "type", "tags", "comment"

    def __init__(self, *args, requiredfields=tablefields, **kwargs):
        super().__init__(*args, requiredfields=requiredfields, **kwargs)

    def __next__(self):
        """ Read one table definition from a csv file.

        Note that this also opens and reads the specification for the table,
        and attaches the spec as an attribute.
        """
        logging.debug("Reading table.")
        table = super().__next__()
        logging.debug("Table spec is at: {}".format(table['spec']))
        with open(table["spec"]) as f:
            table.spec = list(SpecReader(f, requiredfields=self.tableentryfields))
        return table

