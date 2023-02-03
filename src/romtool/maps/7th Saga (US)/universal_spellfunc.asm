; vim: ft=snes
; romtool: patch@9E200:cl65

.P816
.SMART
.ORG $E200 ; not necessary, but helpful for listings

spell_index_start := $C0523A
splfunc_p_dmg := $C4B2F3
splfunc_p_dmg_aoe := $C4B307
splfunc_m_dmg := $C4D3CF
splfunc_m_dmg_aoe := $C4D3E9
first_monster := $1E80

.proc auto_target_damage_func
  SEP #$20
  LDA $927
  CMP $4E
  BEQ continue  ; something is wrong if these two don't match, I think.
  RTL
  continue:

  ; Jump to single or multi as needed. Either way, mimic
  ; existing functions; set accumulator and (re)load spell ID.
  JSR spl_targeting
  CMP #$0
  BEQ dmg_single
  CMP #$1
  BEQ dmg_multi
  ; don't know what to do, so abort, but set accum as usual
  SEP #$20
  LDA $927
  RTL

  ; Jump to player or monster code as needed
dmg_single:
  REP #$20
  LDA $5C
  CMP #first_monster
  BCC p_dmg_single_target
  BRA m_dmg_single_target
dmg_multi:
  REP #$20
  LDA $5C
  CMP #first_monster
  BCC p_dmg_multi_target
  BRA m_dmg_multi_target
p_dmg_single_target:
  SEP #$20
  LDA $927
  JSL splfunc_p_dmg
  BRA return
p_dmg_multi_target:
  SEP #$20
  LDA $927
  JSL splfunc_p_dmg_aoe
  BRA return
m_dmg_single_target:
  SEP #$20
  LDA $927
  JSL splfunc_m_dmg
  BRA return
m_dmg_multi_target:
  SEP #$20
  LDA $927
  JSL splfunc_m_dmg_aoe
  BRA return
return:
  RTL
.endproc

; pass the spell index in the accumulator; replaces it with the
; targeting mode
.proc spl_targeting
  ; store things we'll need to restore later
  PHX
  PHY
  PHB
  PHP
  ; triple the index to get the spell pointer offset within the table
  REP #$30
  AND #$00FF
  PHA
  CLC
  ADC $1, s
  ADC $1, s
  TAX
  PLA
  ; Put the spell data address in y
  LDA spell_index_start, x
  TAY
  ; Set the data bank register to the spell's data bank
  INX
  INX
  SEP #$20
  LDA spell_index_start, x ; spell data bank
  PHA
  PLB
  ; Load targeting byte from spell data address +2
  LDA $0002, y  ; +2 for the targeting byte
  ; Put everything else back the way it was
  PLP
  PLB
  PLY
  PLX
  RTS
.endproc
