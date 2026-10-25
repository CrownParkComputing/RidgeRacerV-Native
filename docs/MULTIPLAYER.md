# Genuine Ridge Racer V multiplayer views

The requested outcome is a view for each participating player when two or more
players race together. Each view must belong to an actual linked cabinet and
share race progression with the others. Duplicated pictures or unrelated
attract-mode instances do not satisfy this requirement.

The RRV3/A dongle's `ACIOPRP` ROMDIR includes:

| Module | Bytes | SHA-256 |
| --- | ---: | --- |
| ILINK | 143093 | `3a3a195d1e9dd559b7236c6ee01d0492852b72432c14b68321b9a25516d23939` |
| ILSOCK | 14953 | `5c4542719060522ba4f2bc8acbe3f2dfc78ea0097699a3fe24d56906fef3300c` |
| ILSAMPLE | 15758 | `f2e4dfff59c23ffb588588d66746974705d5b5127c061125e647a6334108d0a8` |

Static inspection of the original `START` executable found link-play/test and
configuration, ranking, best-lap and sector-time transfer strings. These are
original binary observations, not proof that host-side linking works.

The Ridge ILSOCK export version is 2.2. Its socket queue layout resembles TC3's,
but function/global offsets differ. For example, its receive wait returns to
module-relative `0x2240`, rather than TC3's `0x21a4`. TC3's guarded adapter cannot
simply be enabled for this module, so the foundation carries a separate guarded
`Ridge V RRV3/A` profile. `run_ridge.py --dual-screen` launches the twin-cabinet
supervisor; the transport is live (verified packet exchange, `LINK ON`), but
linked gameplay is still blocked by the course-load crash described below.
Solo launches remove `TC3_CABINET_ROLE`/`TC3_CABINET_DIR`.

Local static analysis established the original module contract:

| Property | Ridge ILSOCK module-relative address/value |
| --- | --- |
| Memory extent | `0x29d0` |
| Open / receive exports | `0x1410` / `0x2428` |
| Receive loop / wait return | `0x21e8` / `0x2240` |
| Socket count / maximum payload | `0x2980` / `0x2984` |
| Socket array / free packet pool | `0x29a4` / `0x29c0` |
| Cached local identity | `0x29b8`, `0x29bc` |
| Original game initialization | 3 sockets, maximum payload 288 bytes |

The original ILSAMPLE module retains its SIF worker symbols. Its Init/Open/Bind/
Connect/Send/SendTo/Recv/RecvFrom imports use the original ILSOCK ABI; retaining
these workers preserves the guest's RPC replies and scheduling. The receive
loop rechecks its original queue after waiting, allowing a narrow host transport
adapter to yield through the original guest `DelayThread` without blocking the
host. A paired runtime test confirmed original connection state 3 on both
cabinets, `LINK ON` in the original service menu, native exchange of original
288-byte game packets and both cabinets entering car/course selection. The
right cabinet subsequently crashed during Park Town loading, so a complete
linked race remains unvalidated; see [STATUS.md](../STATUS.md).

Ridge's connection state is discovered through its original protocol. `LINK AS`
reports the active link side. `PCB ID` is the original service-menu setting used
to choose the requested side. Each cabinet needs independent SRAM, BIOS
companions, memory card and settings; the TC3 lightgun cabinet switch is not a
Ridge identity setting.

Before enabling multiplayer, work must establish:

1. The original RPC/packet and cabinet identity contracts for this Ridge revision.
2. A matching transport with original guest receive scheduling and back-pressure.
3. Independent mutable storage for every participating cabinet.
4. Actual original link status and packet exchange between those cabinets.
5. Multiple credited players entering the same race, with distinct synchronized
   views and correctly routed controls.
6. Shared pause/quit/rendering behavior, race transitions, audio and real game
   rate measured separately from any generated frames.

Linked launch exists but is not validated for gameplay. `tools/run_ridge.py
--dual-screen` starts both cabinets under the supervisor; requirements 1–4
above are met live. Requirement 5 fails today: the right cabinet aborts during
course loading, so no synchronized race has been proven.
`tools/run_ridge_link_test.py --prepare-only --foundation /path/to/foundation`
prepares isolated left/right storage without starting games. Its explicitly
gated `--experimental-link-test` mode is for validating a foundation with the
Ridge module profile and does not certify multiplayer support. Original service
menu identity changes are preserved on repeated preparation.

During a diagnostic, configure the right cabinet using its own original menu:
F9, select `GAME OPTIONS` with Down and Return, highlight `PCB ID`, press Return
to edit, select `2 (RIGHT)` with Down, and confirm with Return. Exit the options
menu and turn off the test switch. Configure the left cabinet as `1 (LEFT)`.
The original FCA-1 menu uses the Up/Down select switches; Left/Right are not its
value editor. The game should show `LINK ON` and matching `LINK AS` sides before
any multiplayer test. Start/coin and racing controls belong to the focused
cabinet in this desktop diagnostic; independent physical controls remain
unvalidated.
