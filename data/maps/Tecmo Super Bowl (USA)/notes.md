# Master index

https://tecmobowl.org/forums/topic/9725-tsb-hacks-documentation-directory-updated-081716/

# Source diving

gmtsb (general manger tecmo super bowl?) -- look in source in the "Core"
directory".l

https://code.google.com/archive/p/tsbtools/source/default/source (look
in tecmotool.cs, specifically:

* GetTeamIndex(string team)
* GetPositionIndex(string? position)
* GetAttributeLocation(teamindex, posindex)
* GetDataPosition(team, position)

getteamindex uses a static list, in rom order, probably will have to
find a corresponding table in the ROM.

posindex = getposindex(position)
guy = teamindex * posnames.length + posindex

Will have to dump separate struct for each "type" of position, I think,
since they seem to use the same data for different purposes.


## Pointer locations ref:

https://docs.google.com/spreadsheets/d/1xq32pN6N6YnaqxfZjsAte1ZK5erqM-IX7PWMadqpjYc/edit?authkey=CI2iiDo&hl=en_US&authkey=CI2iiDo&hl=en_US&authkey=CI2iiDo#gid=0
https://tecmobowl.org/forums/topic/11641-tsb-editing-resources-spreadsheets-tutorials-faqs/

# ROM layout

000-6D0: iNES header information
6D0-2E2C: Player Names
2E2D-3010: Dead Space
3010-3CD0: Player Attributes and Data
3CDC-4010: Dead Space
4010-41F3: Play Formations positioning
41F4-440F: Dead Space
4410-4BF6: Offensive play pointers to specific actions for each player in the play
4BF8-4e09: Dead Space

5010-6000 4x4  metatile drawing info for backgrounds 6010-75FF defensive play command pointers 7600-800F special defensive player pointers (fumble recovery, etc)
8000-9FFF: Specific offensive commands for players
A000-BFFF: Specific defensive commands for players
18163 to 1869F: Simulation code
1D310: Team Default playbooks
1D410-1DA10: Play names and pointers
1DC10: Defensive reaction pointers
27506: Play Graphics pointers

Reference: https://tecmobowl.org/forums/topic/53101-tsb-rom-hex-location-index/


## Something to consider later...

Even for games that don’t use the ASCII standard, editing non-compressed text4
is a relative breeze. Open any ROM in FCEUX and pause on a screen with text.
Opening the PPU Viewer (“Debug” → “PPU Viewer”) displays the game’s alphabet.
Hovering over a letter will display its hex value in the ROM. Saving each
letter and its corresponding hex value (A=80, B=81, etc) as a .tbl file in
WordPad creates what is a called a “table file.” From the hex editor’s file
menu, choose “load .tbl file,” and voila! All the game’s text appears in the
right-hand column.﻿

Ref: https://tecmobowl.org/forums/topic/68955-hacking-tecmo-players-and-stats/

# Displayed stats

Displayed player stats are not actually used mechanically; they're
stored separately at 0x3115c. They're supposed to be some function of
the actual stat, but changes to the displayed stat do nothing. Look that
up later. 

Ref: https://tecmobowl.org/forums/topic/65417-the-location-of-displayed-player-attribute-numbers-61319etc-nes-tsb/

## Sim stats

I keep seeing references to this, I think it's either AI stats or
something to do with simulating games in season mode...

https://tecmobowl.org/forums/topic/10512-applying-sim-data/
