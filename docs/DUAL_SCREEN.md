# Ridge Racer V dual-screen status

`python3 tools/run_ridge.py --dual-screen` launches the linked left/right
cabinet pair through the shared twin supervisor: one machine, two adjacent
no-gap views, one sound source (right worker muted), shared pause/quit/test
state and synchronized EEPROM resets.

## How the link works

Ridge's IOP image ships `ILINK`, `ILSOCK` (v2.2) and `ILSAMPLE`; the original
`START` executable contains link-play/test code plus ranking, best-lap and
sector-time transfer strings. The ILSOCK layout resembles TC3's but with
different function/global offsets, so the foundation carries a separate
guarded `Ridge V RRV3/A` module profile (verified at module base `0x77230`,
socket array `0x10f000`, 288-byte packets).

The transport is a native Unix-socket bridge (`tc3link-left.sock` /
`tc3link-right.sock` under the session directory): each worker's original
ILSOCK receive loop yields through its guest `DelayThread` while a narrow
host adapter moves the game's own packets between workers. Packet builders,
sequence counters and link-command dispatch all run unmodified in the guest —
the bridge only replaces the wire. A real, persistent link state is
established, not merely synchronized UI.

Each worker gets an isolated data-root clone (mutable files copied, large
media hardlinked) and `TC3_PAD_INDEX` assigns physical pad 0 to the left
screen and pad 1 to the right, matching the two cabinet positions.

## Verified live

- Both workers initialize the Ridge ILSOCK modules and report connection
  state 3; the original service menu shows `LINK ON` with `LINK AS 1 (LEFT)` /
  `2 (RIGHT)` after PCB ID assignment.
- Sustained bidirectional 288-byte packet exchange (~2,400 frames each way in
  a 120 s run) at 100% speed, synchronized pause/reset, clean exit 0 on both.
- `Cabinet / Service → Save & Reset Machine` writes the FCAI record with a
  valid checksum and both workers log `synchronized cabinet reset`.

## Blocking issue: linked race crash

Both cabinets were credited and reached car/course selection with a green
Link indicator; the left entered Park Town (`1P` marker visible), but the
right aborted during course loading with the core's `ReadFIFO_VIF1`
assertion (`FQC = 0 on VIF FIFO READ!`). The preserved crash dump places the
guest in a very large `memcpy` whose source reached the FIFO address — this
needs diagnosing the source resource/header state; removing the assertion
would not establish correctness. **A synchronized two-player race is not yet
validated.**

## Still required before claiming linked gameplay

1. Fix the right-cabinet `ReadFIFO_VIF1` course-load abort.
2. Enter the same race on both cabinets and verify distinct synchronized
   views, correctly routed controls and race progression on each.
3. Validate audio, stable 60 Hz real rate and clean shutdown over long runs.
4. Confirm disconnect/loss recovery matches the original hardware.
