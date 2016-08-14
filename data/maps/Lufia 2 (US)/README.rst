Notes on Monsters:

There are four optional fields on monsters: A pointer to their combat
script, a pointer to their resistances, and their drop chance/item.
These optional fields appear at the end of the structure. Monster
scripts tend to start immediately after the optional fields. This means
that adding additional optional fields to a monster is almost certain to
break things by overwriting the start of their scripts.

It should be safe to:

* Remove drops/resists/scripts
* Change the value of a pointer (see below)
* Replace one optional field "type" with another; for example, replace a
  resistance script with a dropped item.

The only useful change you can make to pointer values at the moment is
to point them to a different monster's data. This only works "going
forward"; these pointers cannot be negative so you can't point to
monster data earlier in the monster array. (FIXME: can you finagle it by
deliberately triggering an overflow?) However, you can point to a later
monster's data.  

To point a resistance pointer or combat script to another monster's
data:

1. Start with the target monster's Monster Pointer
2. Subtract the Monster Pointer of the monster you are changing
3. Add the value of the target monster's target pointer.

Or, in math:

tmptr = Target's Monster Pointer
smptr = Source's Monster Pointer
tptr = Target pointer on target monster
nptr = New pointer value

nptr = tmptr - smptr + tptr

