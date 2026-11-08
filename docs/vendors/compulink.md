# Compulink (Compulink_DragRacing, Compulink_DragRacingDetail)

Wiring (catalog): no hardware configuration (direct serial/network text feed).

Frame: ASCII lines ending CR. Bytes outside 0x20-0x7E are removed, lines shorter than 2 chars are ignored (1 char counted as rejected). Tag = first two chars, value = rest.

`C,<category>,<round>` clears every field then sets CategoryName (25), Round (2); (ScoreConnect also sleeps 2 s; not reproduced). Tags: c1/c2 car number (4), b1/b2 class (6), n1/n2 driver (20), m1/m2 member (6), q1/q2 qualifying position (2), S5/S6 dial-in (value after 2 chars, 5), L0-L7 / R0-R7 reaction, 60ft, 330ft, 660ft, 660ft MPH, 1000ft, quarter mile, quarter MPH (6), fl/fr first (6), w- Win (first char), m- Mov (6). Values are truncated to the stated length.

Both ids use the same decoder; Detail sets ChannelNumber '1' and IsDetailed true, the plain one '0'/false (only the sbdata layout differs, in the contract writer). Contract DragRacing, event DragRacing.
