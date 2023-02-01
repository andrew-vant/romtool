; vim: ft=snes
; romtool: patch@9E200
; FIXME: JSL not known by xa, alias it to JSR?

spell_index_start = @$C0523A
single_target_damage_func = @$C4B2F3
multi_target_damage_func = @$C4B307

#define TAB php:sep #$20:pha:plb:plp
#define TSD tsc:tcd
#define mkframe pha:phx:phy:php:phd:tsc:tcd
#define endframe pld:plp:ply:plx:pla

* = $9E200

auto_target_damage_func:
  SEP #$20
  LDA $927
  CMP $4E
  BEQ continue  ; something is wrong if these two don't match, I think.
  RTL
  continue:

  ; Jump to single or multi as needed. Either way, mimic
  ; existing functions; set accumulator and (re)load spell ID.
  JSR @spl_targeting
  CMP #$0
  BEQ single_target_damage_spell
  CMP #$1
  BEQ multi_target_damage_spell
  ; don't know what to do, so abort, but set accum as usual
  SEP #$20:LDA $927
  BRA return
single_target_damage_spell:
  SEP #$20:LDA $927
  JSR @single_target_damage_func
  BRA return
multi_target_damage_spell:
  SEP #$20:LDA $927
  JSR @multi_target_damage_func
  BRA return
return:
  RTL

spl_targeting:
  ; pass the spell index in the accumulator; replaces it with the
  ; targeting mode
  PHX:PHY:PHB:PHP
  ; triple the index to get the spell pointer offset within the table
  .al:REP #$30
  AND #$00FF
  PHA
  CLC
  ADC $1, s
  ADC $1, s
  TAX
  PLA

  LDA @spell_index_start, x:TAY              ; spell data address
  INX:INX
  .as:SEP #$20:LDA @spell_index_start, x:PHA:PLB ; spell data bank
  LDA $0002, y  ; +2 for the targeting byte
  PLP:PLB:PLY:PLX
  RTL
