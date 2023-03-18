; vim: ft=snes
; romtool: patch@595C6:xa65
;
; Patch the original palette routine to jump to the new one.
palette_jump_patch:
  JSR @$C9E100
  RTL
