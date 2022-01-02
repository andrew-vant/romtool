NOTE: for crossref interpretation during load, order matters. Changing
the name of entity A breaks name-references to A from other entities.
Probably referenced entities need to be loaded before those doing the
referencing for names in the input to be consistent -- that is, if
you're changing a name and referencing the new one in the same input
data, the name-change must happen first or lookups will fail.


* update this file
* interpret crossreferences (DONE!)
* enums (DONE!)
* update docs
* remove dead code
* get rid of the registry singletons somehow -- they make testing a
  pain.
  * create metaclass for map-defined types that takes the map as an
    argument, so the type registry(s) become map-local.
  * Actual base structure is abstract
* Better exception organization. Some RomError types should inherit
  ValueError so VE handlers do the right thing.
* Consider not using a monolithic hooks.py file. Each object or type to
  be hooked gets its own file, e.g. codecname.py instead of
  codecname.tbl. (what about fields? Do I need a `fields` directory?)

TODO: how to deal with overlapping data? Indexed tables may have
multiple entries pointing to the same address. Unions implemented as
overlapping struct fields also point to the same address. "Smart"
unions implemented as a single field are a pain to write.

Thoughts:

Overlapping fields: skip empty strings in incoming data. Would have
to be implemented in struct.load; have it ignore empty strings. Then
the user must delete the "wrong" overlapping field when making
changes. Easy on the mapper, harder on the user.

Smart unions: Requires implementation in the map module. Possibly
ok, depends on how hard it turns out to be. Easier on the user,
harder on the mapper. May be un-implementable if the data
determining how the union is used is hard to access.

Duplicate entries in index: Take the first one. Ignore duplicates
that are identical to either the "original" data or the first-row
"changed" data. Warn or error-out if a duplicate row differs from
both.

magic feature: map linter. Things worth checking for:

* correct files w/correct columns
* version mismatches?
* multiple fields deterministically pointing to the same data? (might be
  impossible to statically determine, but such a check on load for
  changesets that hit the same address twice would be nice)

For conf files: partial parse global opts first, check for conf opt, if it's
there read the conf file. Splat the results into the remaining arg
constructors like this: 

    **{default: v for k, v in conf.items() if k == this_argname}

How does this work for position args? Google positional arg defaults

Google fixed-size ints. A lot of my primitive magic stops being a problem if
there's a better library I can inherit from.

Focus on the object tree over serialization. Object tree should include
primitives for all values, with object attributes for pointed-to substructs.
The point is to ensure consistency; if two structs point to the same
substruct, accessing their attributes gets you the same object.

In a lot of ways this is a bit like an internal database. Does python have
built in support for something like that? Offsets as primary keys. A better
way of enforcing constraints and relations would be nice.

(update: Python has built in support for sqlite, but there are problems with
this approach. I could use database constraints to enforce consistency between
objects (e.g. using foreign keys, or range restrictions) but there is no
guarantee that the game as released has consistent object relationships! OTOH,
being able to produce output using some variant of select statements could be
quite useful.)

Serialization then becomes something like "serialize all my substructs, then
serialize my attributes, order by (something)." Consider an intermediate
serialization (yaml?) that is easy to convert to e.g. CSV. Yaml has object
links, so maybe don't serialize the substruct, include an object link instead.
(how do we uniquely identify substructs? probably their offsets) Only flatten
when converting to CSV.

How to deal with substructs? Should probably be an object link, but then how
to deal with matching object links when serializing? Structs don't know about
them and the next level up shouldn't have to parse serialization to figure out
whether links match.

Structs should save their offset; reassigning a substruct should have a
setattr hook that updates pointers, so rewriting still works. Try not to
support updating pointers directly (but "find object by offset" might be a
good idea, as would "create new substruct with new offset in safe space", if
possible). When deserializing/unflattening, make an offset->substruct dict. If
a parent struct points to a substruct, add the new substruct to the dict; if
that same pointer is encountered again, check that the intended value matches
what's in the dict, if not crash, if yes use the dict's object instead of
building a new one. This should ensure consistency on deserialization.

Make (str) return a yaml representation.

* enums
* names for crossreferences
* custom text codecs
* build should merge patch sources
  - These might be dump spreadsheets or might be existing patches
