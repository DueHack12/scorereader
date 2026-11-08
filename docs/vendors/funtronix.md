# Funtronix (`scoreboards/funtronix.py`)

Id: `Funtronix_Autodetect`. Wiring (catalog): RS-232, 9600.

## Framing
16 bytes: byte 0 has bit 7 set, bytes 1-15 do not. A frame with another bit-7 byte inside is rejected (this port resyncs one byte on; ScoreConnect skips all 16). Leading bytes without bit 7 are dropped. No checksum.

## Autodetect
`byte0 & 0x60`: `0x40` basketball, `0x00` soccer, `0x20` volleyball. `0x60` is ignored (nothing decoded until a known code). A change of code builds a fresh decoder (state cleared). All digits are the low BCD nibble (A-F = blank).

## Common clock
Byte 8 bit 4 set: mm:ss from 8,9,10,11 (mode `:`, tenths `0`); else ss.t from 10,11,12 (mode `.`).

## Basketball
Flags in byte 0: 8 HomePossession `<`, 4 GuestPossession `>`, 2 HomeBonus, 1 GuestBonus. Home score hundreds/tens/ones = bytes 3,2,1; guest = 6,5,4; Period 7; ShotClockSecondTens/Ones 14,15.

## Soccer (contract `Soccer`)
Flags: 8 HomePossession `<`, 2 GuestPossession `>`. Home score tens/ones = 2,1; guest 5,4; Period 7; HomePenalties 13; GuestPenalties 15.

## Volleyball (contract `Volleyball`)
Flags: 8 HomeServe `*`, 4 GuestServe `*`. Scores as soccer; Game 7; HomeGamesWon 13; GuestGamesWon 15.
