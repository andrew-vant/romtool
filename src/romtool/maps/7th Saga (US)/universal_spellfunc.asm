; vim: ft=snes
; romtool: patch@9E200
; FIXME: JSL not known by xa, alias it to JSR?

spell_index_start = @$C0523A
splfunc_p_dmg = @$C4B2F3
splfunc_p_dmg_aoe = @$C4B307
splfunc_m_dmg = @$C4D3CF
splfunc_m_dmg_aoe = @$C4D3E9
first_monster = $1E80

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
  BEQ dmg_single
  CMP #$1
  BEQ dmg_multi
  ; don't know what to do, so abort, but set accum as usual
  SEP #$20:LDA $927
  RTL

  ; Jump to player or monster code as needed
dmg_single:
  .al
  REP #$20:LDA $5C
  CMP #first_monster
  .as
  BCC p_dmg_single_target
  BRA m_dmg_single_target
dmg_multi:
  .al
  REP #$20:LDA $5C
  CMP #first_monster
  .as
  BCC p_dmg_multi_target
  BRA m_dmg_multi_target
p_dmg_single_target:
  SEP #$20:LDA $927
  JSR @splfunc_p_dmg
  BRA return
p_dmg_multi_target:
  SEP #$20:LDA $927
  JSR @splfunc_p_dmg_aoe
  BRA return
m_dmg_single_target:
  SEP #$20:LDA $927
  JSR @splfunc_m_dmg
  BRA return
m_dmg_multi_target:
  SEP #$20:LDA $927
  JSR @splfunc_m_dmg_aoe
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
