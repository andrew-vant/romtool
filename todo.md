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
