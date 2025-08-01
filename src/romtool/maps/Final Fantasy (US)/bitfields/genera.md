Monster generas.

Of the three uses of this bitfield, two of them are bugged.

1. Some weapons are supposed to get bonuses vs. certain monster types
   (bugged, does nothing).
2. Regenerative monsters are supposed to regenerate HP (bugged, does
   nothing).
3. Some spells only affect undead (this one works).

In practice this means the only bit that matters is the undead bit.
