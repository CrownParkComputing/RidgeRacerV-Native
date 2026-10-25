# Original cabinet test controls

Press **F10 → Cabinet / Service**. The shared Nuklear menu offers two layers:

## Direct service settings (recommended)

Game cost, continue cost, GP winner service (solo/link), free play, select
speed, course choice and speed display are edited directly in the menu — the
original test menu is not needed for ordinary changes. **Save & Reset
Machine** writes the `FCAI` EEPROM record with a valid byte-sum checksum and
reboots both linked cabinets together so they always run identical settings.

| Action | Original board control |
| --- | --- |
| Service credit | Original service switch |
| Insert coin | Original coin input |

Fields still only reachable through the original test pages: entry wait, laps,
COMCAR difficulty, PCB ID and course select — their EEPROM encodings are
partially mapped but not yet verified for direct writes.

## Original test menu (diagnostics)

**F9** toggles the original JVS test DIP on both linked screens. Arrows move
the selection, **Return** selects/confirms, **9** service credit, **5** coin,
and **START** exits a page or the test mode itself. Use the game's own I/O
test for steering wheel and pedal checks; finish its original exit/save
procedure so option writes commit cleanly.

Ridge's EEPROM store is a tagged-record format: the `FCAI` record at `0x08`
carries option bytes and a `u16` byte-sum checksum at `0x00`; a bad checksum
makes the game restore factory defaults, which is why the native writer
recomputes it on every change. The linked cabinet pair is documented in
[dual-screen status](DUAL_SCREEN.md) and [multiplayer notes](MULTIPLAYER.md).
