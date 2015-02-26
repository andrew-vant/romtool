ureflib
=======

known requirements:
- bitstring
- patricia-trie

array type field: type name, which can be a primitive or a struct, and if primitive a column label for the output data (separate column, optional?)

arrays.csv specifies the arrays in a ROM and their types. Some separate table (objects.csv?) specifies which arrays to unpack, which to splice together as a single object, and maybe text-decoding information? Something like: 

object,arrays,outfile,preprocess,postprocess 

With pre/post process doing things like decoding text and converting pointers. 

STRUCTS: Can bitstream extend its types with user-specified ones? Can I take a struct csv and turn it into a bitstream type? (answer: No, but we might be able to turn a struct into a format string.) 

Note: The library isn't responsible for deciding what to unpack. That's the application's job. 

Handling pointers: We need some way of saying "this is a pointer of type hirom/lorom/whatever to an object of type whatever", and also for deciding whether to dereference it or not. The difficulty here is primitives, where we need to know both the size of the pointer and the size of the pointed-to object. Not sure of the right way to handle this. 

Features I want:

1. I want to be able to extract tables from the ROM and put their contents in .csv files for editing. (I already know how to do this, mostly)
2. I want to be able to merge disparate tables and arrays into a single .csv when that makes logical sense. For example, your ogre battle horribleness where there were multiple arrays of scalars for different stats instead of a single array of structs. I don't have this figured out yet. 
3. I want to be able to inspect the rom for the labels that apply to entries in those tables; e.g. if I have a table of monster data, I want to know which entry corresponds to each monster even if the table itself doesn't contain the name. I had this working for 7th Saga but the technique didn't generalize when I tried other games, so I need to try again.
4. I want to be able to extract text from the ROM into text files or some other format that makes sense. I sort-of-know how to do this; I had it working before but the output wasn't ideal. It's related to #3. 
5. I want to be able to take changes to those csvs and text files, compare them to the original rom, and generate an appropriate patch. I had that working before for data structures but not for text. 

Low-level things that need doing:

1. Read a single scalar.
2. Read an entire struct. 
3. Dereference a pointer in a struct.
4. Associate multiple scalar or struct arrays in numerical order. 
5. Decode a character
6. Encode a character

more...

Modules:

map (loads and interprets ROM maps)
text (contains encode/decode functions for single characters and strings)
binary (reads scalars or structs, raw data, given a structdef)
pointers (pointer differences are horrible, I *need* to abstract them)
csv (turns struct(s) into an appropriate output format, reads csvs into arrays)
patch (binary diff functions, ips generation)

