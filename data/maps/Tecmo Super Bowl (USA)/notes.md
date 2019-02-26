# Master index

https://tecmobowl.org/forums/topic/9725-tsb-hacks-documentation-directory-updated-081716/

# Figuring out which roster players have which stat sets

Looks like this might be derivable from the "formation" data. One
of the editors has a formationtorosterpositionsmapper that gets
checked when figuring out which player has which position, which in
turn defines the attribute set to use.

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

```
# See gmtsb/src/org/twofoos/gmtsb/file/tsbfile.java and
# supplementednesfile.java. These seem like the most useful files
# for finding offsets and data formats.

HEADER_LENGTH                                16;
TEAM_POINTERS_LOCATION                       (HEADER_LENGTH);
FIRST_TEAM_PLAYER_POINTER_LOCATION           (56               +  HEADER_LENGTH);
FIRST_PLAYER_NAME_LOCATION                   (1738             +  HEADER_LENGTH);
PLAYER_ATTRIBUTES_LOCATION                   (0x3000           +  HEADER_LENGTH);
FORMATION_POSITION_SECTIONS_LOCATION         (0x0021fe0);
FORMATION_POSITION_LABELS_LOCATION           (0x0031e80);
PLAY_NAMES_FORMATIONS_AND_POINTERS_LOCATION  (0x001d410);
DEFENSE_REACTIONS_LOCATION                   (0x001dc10);
PLAY_GRAPHICS_LOCATION                       (0x0027546);
PLAY_BALLCARRIERS_LOCATION                   (0x0027506);
PLAYBOOKS_LOCATION                           (0x001d310);
FIRST_TEAM_NAME_POINTER_LOCATION             (0x001fc10);
FIRST_TEAM_NAME_LOCATION                     (0x001fd00);
SPRITE_COLORS_LOCATION                       (0x2c2e4);
CUTSCENE_COLORS_LOCATION                     (0x342d8);
PLAYER_DATA_COLORS_LOCATION                  (0x31140);
RETURNERS_LOCATION_1                         (0x00239d3);
RETURNERS_LOCATION_2                         (0x00328d3);
PRO_BOWL_PLAYERS_LOCATION                    (0x0032853);
SIMULATION_CODE_LOCATION                     (0x0018163);
RUN_PASS_RATIO_LOCATION                      (0x0027526);

public final int MAX_TOTAL_NAMES_LENGTH = PLAYER_ATTRIBUTES_LOCATION.subtract(FIRST_PLAYER_NAME_LOCATION);

public static final int TEAM_SIMULATION_CODE_SIZE_BYTES = 48;
public static final int TEAM_SIMULATION_CODE_SIZE_NYBBLES = TEAM_SIMULATION_CODE_SIZE_BYTES * 2;
public static final int TOTAL_SIMULATION_CODE_SIZE_NYBBLES = TEAM_SIMULATION_CODE_SIZE_NYBBLES * League.NES_TEAMS_COUNT;

// http://www.knobbe.org/phpBB2/viewtopic.php?t=1820
public final TsbLocation FORMATION_POSITION_SECTIONS_CODE_LOCATION	(0x0021642);
public final TsbLocation FORMATION_POSITION_LABELS_CODE_LOCATION	(0x0030ff8);

public final int[] FORMATION_POSITION_SECTIONS_CODE_PATCH =
    new int[] { 0x8a, 0xa6, 0x6e, 0xbc, 0xd0, 0x9f, 0xaa, 0x4c, 0x50, 0x96,
        0xf0, 0x12, 0xc9, 0x11 };
public final int[] FORMATION_POSITION_LABELS_CODE_PATCH =
    new int[] { 0x8a, 0xa6, 0x6e, 0xbc, 0x70, 0x9e, 0xaa, 0xc0, 0x01, 0xf0,
        0x11, 0xc0, 0x02, 0xf0, 0x13, 0x4c, 0xfe, 0x8f, 0xc9, 0x11, 0xf0,
        0x0c, 0xbd, 0x39 };
```


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
