; This is intended to replace the contents of the routine that sets
; spell palettes. It's longer than the original routine, so put this
; elsewhere and have the original call it with JSL.
;
; Specifying a spell palette in the table will override whatever the
; spell's graphics script normally sets. Table is one byte per spell, in
; the same order as the main spell data table.
palette_set_original = @$595C6
spell_palette_table = @$C9E000
palette_40_and_y_to_1DB0 = @$2920F

palette_set_replacement:
  .as
  .xl
  SEP #$20
  LDY #$0000
  LDA #$0E

  ; CHANGES START HERE
  PHA
  PHX
  PHY
  LDA $927
  CMP $4E
  BNE exit_palette_lookup
  SEP #$10
  TAX
  LDA @spell_palette_table, x
  REP #$10
  CMP #$FF
  BEQ exit_palette_lookup
  STA $40
  exit_palette_lookup:
  PLY
  PLX
  PLA
  ; CHANGES END HERE

  .byt $22,$0F,$92,$02 ; palette_40_and_y_to_1DB0
  SEP #$20
  LDA #$0C
  STA $1E,X
  LDA #$04
  STA $1D,X
  LDA #$30
  STA $0E,X
  RTL


