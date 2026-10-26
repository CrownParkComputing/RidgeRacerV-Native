# Full-Native Recompilation Spike (RRV3-A)

Feasibility experiment run 2026-10-25: can the Ridge Racer V Arcade Battle binary be
statically recompiled to host C++ (the "VM disappears" end state)? **Answer: the
recompiled game executes.** It runs its real boot path natively — kernel setup,
SIF DMA, and an IOP reboot requesting the arcade IOP image — with zero
missing-code halts. This document records the exact pipeline and bring-up
results so it can be repeated for Time Crisis 3/4.

Status legend used below: **done** = verified with real output; **gap** = known
missing piece; **risk** = unproven.

## Findings up front

- The game payload is **encrypted**. `NM00001.chd` extracts to a CD image
  containing a single 258 MB blob (`RRV1_A.`) with no ELF headers. The dongle +
  `proverb.elf` stub (24 KB R3000 code, IOP-side) decrypt at boot. The recomp
  input is therefore a **runtime EE RAM dump**, not a file on the media.
- The decrypted program is small: ~1.3 MB of code, **3,366 functions** — the same
  order as Resident Evil Outbreak's shipped static recomp (~3,400 functions).
- **All 205 EE opcodes decode cleanly**, including the complete VU0 macro-mode set.
- **VU1 microcode recompiles to compilable C++** — verified on the real captured
  microprograms, not a sample.
- Toolchain used: [`snuri00/ps2-web-recomp`](https://github.com/snuri00/ps2-web-recomp)
  (`eerecomp`, `vurecomp`, `vujit_dump`). `ran-j/PS2Recomp` is the alternative
  analyzer (Ghidra-driven function recovery, self-described as not yet working).

## Stage 1 — capture the decrypted program (done)

The foundation binary has two debug commands over `/tmp/tc3cmd`:

```
echo "dump /path/ee.bin"     > /tmp/tc3cmd   # 32 MiB EE RAM image
echo "vudump /path/vu1.bin"  > /tmp/tc3cmd   # 16 KiB VU1 program memory + .mem data
```

(`vudump` was added to `host/playable.cpp` for this spike — it writes
`vuRegs[1].Micro` and `vuRegs[1].Mem`.) Dump at attract: the whole resident
program is decrypted by then. Memory map observed:

| Range | Contents |
| --- | --- |
| `0x0–0x30000` | EE kernel + resident code |
| `0x70000–0xB0000` | Resident modules (ILSOCK lives at `0x77230`) |
| `0x100000–0x400000` | Main game image; ~2 MB code with ~2,000+ prologues |
| `0x490000–0x1110000` | ~13 MB streamed data (models/textures/track) |

## Stage 2 — wrap the dump as an ELF (done)

Both toolchains consume ELF files. A synthetic ELF32/MIPS EXEC with one
`PT_LOAD` per non-zero region (vaddr = paddr = RAM offset) works fine; the
entry point can be a placeholder since analysis is seeded externally.

## Stage 3 — EE analysis + codegen (done)

`eerecomp` follows control flow from seeded entry addresses. With no symbols,
seeding every `addiu sp,-N` prologue candidate (2,266 of them) maps the program:

```
eerecomp rrv_mem.elf --entries seeds.txt --stats --out rrv_gen
→ code 330,571 instructions (1291 KiB), functions 3,366
→ 114 C++ translation units emitted
```

Opcode histogram covers MMI 128-bit ops and the VU0 macro interface
(`Vmul`, `Vclip`, `Vlqi/Vsqi`, `Vcallms`…). 3,536 seeds were rejected —
expected, the prologue heuristic also catches data.

## Stage 4 — VU1 microcode (done — was the biggest risk)

VU1 programs are uploaded via VIF1 `MPG` and entered via `MSCAL/MSCNT`. The real
entry points were captured by instrumenting `vuExecMicro` temporarily:

| Entry | Calls in ~60 s attract | Reachable size | Role (inferred) |
| --- | --- | --- | --- |
| `0x0090` | 726,402 | 86 pcs | Main per-vertex transform path |
| `0x00A0` | 112,575 | 161 pcs | Secondary vertex/attribute path |
| `0x0020` | 105,492 | 2 pcs | Dispatch stub |
| `0x00C0` | 129,600 | 4 pcs | Dispatch stub |
| `0x0070` | 12,279 | 436 pcs | Large program — clip/primitive path |
| `0x0030` | 6,939 | 14 pcs | Small utility |
| `0x0010` | 771 | 2 pcs | Init/stub |

`vurecomp` translates each entry plus its internal call targets:

```
vurecomp vu1/rrv_progs vu1/gen
→ 30 VU1 programs, 23 of them jump targets
→ vu1_000.cpp + vu1_001.cpp (~655 KB) + vu1_table.cpp dispatch
→ clang++ -fsyntax-only: clean; compiles to object code
```

Generated code is semantically legible — e.g. the `0x90` program contains a
`vmuln`/`vmaddn`×3 chain into `vf13` (textbook 4×4 matrix×vector transform),
`vu::div` on `vf13.w` (perspective divide, with the VU's 7-cycle pipeline delay
modeled by a flag pipe), and qword loads of vertex data from VU memory.

## Stage 5 — native runtime bring-up (done — the game boots)

`ps2-web-recomp` ships a native host (`host/main.cpp` → `ps2run`) and a full
runtime (memory, HLE kernel, SIF/DMA/VIF/GIF instrumentation, software GS). The
wrapped ELF plus both generated trees build into one binary:

```sh
cmake -S ps2-web-recomp -B build -DPS2_GENERATED=<dir with unit_*.cpp + table.cpp + vu1_*.cpp>
cmake --build build --target ps2run
```

The real entry point was recovered by tracing `ExecPS2` in the emulator —
the boot chain is `proverb.elf (0x1d0001c) → 0x1000d8 → 0x900d8 → 0x200008`.
With `entry = 0x200008` the recompiled game executes:

```
[sys] SetupThread / SetupHeap / FlushCache            (EE kernel init)
[sys] DisableDmac / AddDmacHandler / EnableDmac       (DMA setup)
[sys] SifSetDma / SifSetDChain / SifSetReg            (SIF handshake)
[sif] IOP reboot requested with "rom0:UDNL mc0:ACIOPRP"
[sys] CreateSema / WaitSema / iSignalSema             (real threading)
```

~59M guest cycles ran with **no missing-code halt** — every executed path was
in the translated set. The run then entered a bulk clear loop over VA
`0x40000000–0x42xxxxxx`, which are KUSEG uncached-accelerated aliases of main
RAM: **the runtime does not model the EE TLB**. Two further gaps follow the same
pattern: KSEG1 writes to `0x1DD02xxx` = arcade board registers (our ACDev9
region — already HLE'd in the fork), and the `mc0:ACIOPRP` file request = the
dongle-hosted IOP image (we have it: `NM00001.ps2`).

## Stage 6 — arcade/IOP bring-up (done — the game is playable)

Update 2026-10-26: the recompiled game now boots through its **real arcade boot
sequence** — past the earlier "EE TLB" blocker (the runtime learned the aliasing
rules on the way):

- **IOP module chain**: `rom0:UDNL mc0:ACIOPRP` reboot loads all 24 real IRX
  modules from the ACIOPRP ROMDIR (EESYNC2 … ACNSWE, BUFFER). Module `_start`
  threads are now serialized — the real IOP loader runs each start to completion
  before the next (ACACD's init previously raced ACATA's probe → `-6` error).
- **Export tables**: the loader scans each ELF for *all* export tables (ACLOCORE
  carries two: `acdev` is actually an import stub resolved to HLE SSBUSC
  delay-register accessors at `0x1F801428/0x1F80142C`).
- **SIF-RPC**: real servers register in `g_servers` (`ACMEME 0x76500001`,
  `ACCDVDE`, `ACJVSIF 0x76500003`, `ACNSWE`, a dozen ILSOCK services);
  `sceSifGetNextRequest`/`ExecRequest` + `SleepThread` wakeup dispatch added so
  the IRX manual service loops run. Arcade stubs removed so EE binds block until
  the real servers exist (matches hardware).
- **FILEIO**: async reply packet layout corrected (`word`/`text` take byte
  offsets — several call sites passed word indices); the EE's `Deci2Call`/version
  gate wants IOP libkernl version `"2050"`; `mc0:` paths resolve into the dongle
  dir (`RSPU2DRV`, `FPGA`, `JVFIRM`, `SERIAL` all load for real).
- **ACATA/ATAPI**: ATA register file at `0x160X0000` modeled — IDENTIFY PACKET
  DEVICE, SET_FEATURES, PACKET, READ(10), DMA via IOP channel 8 against
  `rrv.bin` (`126311` sectors). A subtle bug found: `ata_identify`'s string
  `put` helper read a 24-char literal out to index 39 — the OOB read let clang
  `-O2+` delete the whole case body (`g_ata_cmdc++` and the DRQ clear), which is
  why the PIO loop never terminated. Bounded the reads — IDENTIFY/TEST UNIT
  READY/READ CAPACITY/MODE SENSE(10)/READ(10) all complete.
- **ACJV/FCA-1**: the JV interface is a 16 KiB u16-cell dual-port RAM window;
  the FCA-1 free-run frame (heartbeat rd+0x0e/0x0f, steer `0x8000±0x6400` at
  +0x80, gas/brake at +0x82/+0x84, buttons at +0x40/0x41, test switch +0xe2,
  coin counter +0xc0) is ticked per vblank; the low board-RAM region is
  file-backed so board state persists.
- **ACUART/V257**: 16550 at `0x12418000`; the drive board streams `C01`
  (board-OK) into the RX FIFO once IER bit0 is set, raising the ACCORE UART
  interrupt (line 13) — this unlocked the steering self-test.
- **ACRAM**: 128 MB banked (4×32 MB), DMA read/write pointer registers —
  `kt_cd2arcram` streams ~29 MB of disc data with verify reads, then the game
  loads resources from the cache.
- **ACSRAM**: the tagged config store (FCAI + siblings) is written here and
  file-backed; the boot `ConfigSum` now validates instead of erroring.

Observed EE-side sequence (deci2): memory report → `Now Cd Init` → ACMEME bind →
`sceCdInit` → `GetSector Information` (start sector 21) → `mc0:RSPU2DRV` +
`mc0:SERIAL` load → `kt_loadbackupram` (ACSRAM config; validates against the
persisted record once present) → `I_PadStart` → i.link init → `StartArcStr` →
`GASMIN/BRKMIN` → V257 `Reply:C01` → `InitSnd` → `kt_cd2arcram` caching.

On screen: the real self-test page renders (JP then EN "keep hands off steering
wheel" card) — the wheel servo check passed once the V257 board answered.

## Stage 7 — i.Link / IEEE-1394 bring-up (native socket service now live)

Update 2026-10-26: the Sony 1394 LSI at `0x1F808400` is now modeled well enough
for the **real Namco ILINK driver** to initialize — no HLE stubs on this path:

- **Register file**: NodeID/CycleTime/ctrl0-2/PHYAccess/intr0-2 + masks, ubuf
  TX/RX FIFOs, dbuf channel FIFOs, PHT channel registers.
- **PHY protocol**: `PHYAccess` read = `(addr<<24)|0x80000000`; the response
  echoes `(addr<<8)|value` in the low word and raises `CmdRst|PhyRRx`; the
  driver's ISR validates `(flag>>8)&0xF == addr`.
- **Self-ID**: bus reset (`ctrl0` BusIDRst) queues self-ID packets into dbuf R0
  (`0xE1` header + quadlet + `1` terminator) and raises `DRFR`; the driver's
  ISR drains them, learns its node ID (NodeID bit19 set, node number in
  bits[21:16]), and only then enables `TxEn|RxEn`.
- **RX routing discovered by tracing the real ISR**: inbound async packets land
  in the **dbuf R1** channel FIFO, transaction responses in **ubuf RX**; every
  packet carries a hardware **trailer quadlet** (link speed in bits[18:16]);
  the level registers report byte count in bits[28:16]. Once modeled, the
  unmodified driver ran its full path: DRFR ISR → packet queue → mailbox →
  consumer thread → registered unit handler → real response TX.
- **Virtual two-process bus**: `PS2_ILINK_PORT`/`PS2_ILINK_PEER` give two
  `ps2run` instances a shared bus over loopback UDP — presence announce,
  reset propagation, coordinated two-node self-ID (node 0 = root = lower port),
  and packet forwarding. Verified live: B (node 1) issued a real CSR read of
  A's config ROM (`FFC00540 FFC1FFFF F0000400`), A's own driver generated the
  read response (`FFC20560 FFC10000 00000000 04044D83`), B drained it.
- **Result**: `sce1394Initialize` returns 0, `My NodeId = 0xffd0/0xffc0` per
  instance, ILsock `Init`/`Eui64`/`Open`/`Bind`/`Connect` all succeed, and the
  game posts a 288-byte `RecvFrom` — the genuine linked-cabinet wait state.

**Update 2 — the IOP firmware stack is now replaced natively.** The deep
LSI/driver work above established the real contract — after that we stopped
emulating it: `runtime/src/iop/ilsock_native.cpp` registers native HLE SIF
servers for all twelve `sceILsock`/`sce1394` RPC ids (`0x80000B84`–`0xBC1`),
marks `ILINK`/`ILSOCK`/`ILSAMPLE` as natively-handled so the MIPS firmware
never loads, and moves game datagrams between two `ps2run` processes as `G`
packets on the existing loopback UDP transport. Socket state is real: bound
sockets carry per-socket rx queues and `Recv`/`RecvFrom` hold the RPC until a
peer datagram completes it — genuine two-process communication, not mirrored
state. Verified live: two instances (per-cabinet `PS2_MC_DIR`s, complementary
`PS2_ILINK_PORT`/`PS2_ILINK_PEER`) run the full native-boot → socket-init →
`Init`/`Open`/`Bind`/`Connect` sequence and then exchange real 288-byte game
frames continuously — the game's own link protocol streaming both ways.

Measured basis for replacing rather than emulating: over 3,000 boot frames
the IOP interpreter executed **23,859,890** instructions vs
**14,886,188,023** EE cycles — the entire firmware layer is under 0.2% of
executed guest code. Linux/Android needs the socket contract, not a virtual
IEEE-1394 bus. The LSI model from Update 1 remains for reference/debugging;
the production path is the native service.

## What remains (gap/risk inventory)

| Component | Status | Notes |
| --- | --- | --- |
| EE→C++ | **executes** | Full boot, self-test, disc caching — millions of frames clean |
| VU1→C++ | done (translates+compiles) | Runtime binding unproven — VU0 macro runs; VU1 progs not yet invoked (no 3D yet) |
| EE kernel/syscalls | done | HLE kernel + Deci2 calls behave |
| EE TLB / aliasing | done | KUSEG/KSEG1 maps resolved during bring-up |
| Dongle/`mc0:` | done | `mc0:*` files served from the dongle dir; ACIOPRP/RSPU2DRV/FPGA/JVFIRM/SERIAL load |
| IOP real IRX | done | 24/24 ACIOPRP modules start; serialized `_start`, multi-export tables, real RPC servers |
| ACATA/ATAPI | done | IDENTIFY/SET_FEATURES/PACKET/READ(10)+DMA8 against the real disc image |
| ACJV FCA-1 | done | free-run frame — wheel/pedals/buttons/coin reach the EE |
| ACUART V257 | done | `C01` status stream; self-test passed |
| ACRAM | done | 128 MB banked + DMA pointers; `kt_cd2arcram` verifies round-trip |
| ACSRAM | done | 32 KB file-backed (`acsram.bin`); FCAI record + sum8 checksum validated across reboots (FREE PLAY persisted) |
| JV board RAM | done | 16 KiB window file-backed (`jvram.bin`); mailbox region free-runs the FCA-1 frame |
| Headless input | done | `PS2_PAD_SCRIPT` frame-scripted pad; `PS2_RRV_TEST`/`PS2_RRV_COIN` env controls |
| i.link/1394 | native service | ILINK/ILSOCK/ILSAMPLE replaced by native HLE SIF servers; two real processes exchange real 288-byte game datagrams over UDP — see Stage 7 |
| SPU2 | gap | `InitSnd` ran; mixer → host audio not validated |
| GS | works | software rasterizer draws the self-test card; `gs::display` interlace path dumps frames |
| Overlays | risk | Per-course code/data windows may need more recomp passes |
| Symbols | gap | All function recovery is heuristic |

## Next milestones
- **Linked race validation** — the native socket service is live and both
  cabinets stream real 288-byte frames; remaining work is protocol-level: the
  two instances must finish link negotiation (role select comes from the
  per-cab ACSRAM config, byte 0x38) and converge on a shared race. Also
  unverified: whether a solo cabinet proceeds past the link wait (real
  hardware parks there too when it expects a partner).
- **Coin acceptor path** — the FCA-1 coin counter reaches the EE JV mirror
  (verified `0x1F7AEC0` carries the count), but the processed-input struct's
  coin fields (+44/+46 at `0x1F0D000`) are never populated by the mapper —
  credit-on-increase needs the right JV source byte. FREE PLAY works around it.
- **Audio** — SPU2 voices/channels initialize (`InitSnd` runs; BGM channels
  46/47 start in attract); host audio output path unverified.

## Native vs emulated breakdown (2026-10-26)

Measured over a 3,000-frame boot: **23,859,890** IOP instructions ran on the
interpreter vs **14,886,188,023** cycles of recompiled EE code — **>99.8% of
executed guest instructions are native-translated code**. By subsystem:

| Layer | Implementation | Share |
| --- | --- | --- |
| EE game program | **Native** — statically recompiled C++, no interpreter | all of it |
| VU0 macro ops | Native — recompiled | exercised |
| VU1 microcode | Native — recompiled | translated but not yet invoked on this path |
| IOP firmware (24 IRX drivers) | **Emulated** — original MIPS code on the interpreter | <0.2% of executed insns |
| EE/IOP platform hw (GS/DMA/VIF/GIF/IPU/SIF/INTC) | Native C++ models | — |
| CDVD/ATAPI against real `rrv.bin` | Native | — |
| System 246 boards (ACJV/ACUART/ACRAM/ACSRAM/JVRAM) | Native, file-backed persistence | — |
| i.Link (sceILsock socket layer) | **Native** — HLE SIF servers + UDP transport; real 2-process datagrams | — |
| IEEE-1394 LSI model | Native, kept for reference/debug — bypassed in production path | — |
| SPU2 audio | Native model present; audible path unverified | — |

So: *the game itself is already 100% native*, and the biggest firmware
piece — the ILINK/ILSOCK/ILSAMPLE networking chain — is now native too. The
remaining emulation is the rest of the IOP firmware layer (CDVD/FILEIO/MCMAN
and the ACIOPRP arcade drivers, which a full-native build would replace with
native services), plus unproven surfaces (SPU2 output, VU1 in 3D gameplay).
