# Full-Native Recompilation Spike (RRV3-A)

Feasibility experiment run 2026-10-25: can the Ridge Racer V Arcade Battle binary be
statically recompiled to host C++ (the "VM disappears" end state)? **Answer: the
two highest-risk stages both produce working output.** This document records the
exact pipeline so it can be repeated for Time Crisis 3/4.

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

## What remains (gap/risk inventory)

| Component | Status | Notes |
| --- | --- | --- |
| EE→C++ | done (analysis) | Runtime bring-up untested — EE kernel syscalls, DMA/VIF/GIF hardware answers |
| VU1→C++ | done (translates+compiles) | Runtime binding (register/mem layout, XGKICK handoff to renderer) unproven |
| GS | gap | Needs a GS-packet→Vulkan runtime library; PCSX2's GS core or paraLLEl-GS are the candidates. No VIF/FIFO timing needed in recomp |
| IOP/IRX | gap | ILSOCK/mempool etc. run on IOP (R3000); interpreter-per-module or HLE. Our native AN986/ILSOCK map already exists |
| SPU2 | gap | Software mixer → host audio |
| Overlays | risk | Per-course code/data windows; `eerecomp --overlays` handles captures, needs per-window seeds |
| Board layer | done | JVS, FCAI EEPROM, AN986 link, cabinet control — all already native, ports forward unchanged |
| Symbols | gap | All function recovery is heuristic; a Ghidra pass over `rrv_mem.elf` would improve boundary quality |

## Recommended next milestone

Small runtime bring-up spike: link `rrv_gen` + `vu1/gen` against a minimal host
(memory map + syscall stub table + VU dispatch) and push the game to its first
JVS/ILSOCK call or first GS packet. That tests whether the *runtime* — not the
translation — is where the real cost sits.
