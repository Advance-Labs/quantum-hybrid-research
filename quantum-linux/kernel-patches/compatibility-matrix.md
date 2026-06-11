# QuantumLinux Compatibility Matrix — Stage 5 (annotated for QLOS v0.1)

**Document:** quantum-linux/kernel-patches/compatibility-matrix.md
**Deliverable of:** workflow Stage 5 (docs/workflows/02-linux-workflow.md, steps 4–5)
**Class source of truth:** the Feasibility Classification table of the research doc
(docs/research/02-quantum-linux.md). Every `Class` value below is copied from that table with
**zero deviations**; the `Research-doc rationale` column cites each row's one-line rationale.

Classes: **(A)** directly portable · **(B)** quantum-aware rewrite · **(C)** classical
emulation layer · **(D)** fundamentally incompatible.

**QLOS v0.1 status** (three-state annotation of what this repo actually implements vs defers):

- **implemented-in-v0.1** — running, tested code in this repo (`emulator/qcpu.py`,
  `toolchain/qas.py`/`qdis.py`, `qos/qsyscalls.py`/`scheduler.py`, `examples/`, and the
  Stage 5 harness `emulator/test_kernel_init.py`);
- **specified-only** — the contract exists (`kernel-patches/qsyscall.h`,
  `qos/QLOS-DESIGN-v0.1.md`) but v0.1 ships no executable model of it;
- **impossible** — no implementation can exist on any hardware; the row names the
  **[Proven]** physical law (these are exactly the research doc's class-D rows).

| # | Kernel component | Class | Works in this repo? | QLOS v0.1 status | Mechanism | Research-doc rationale |
|---|---|---|---|---|---|---|
| 1 | Boot / init (`start_kernel`) | A | Yes — exercised by the Python harness: `emulator/test_kernel_init.py` drives the scripted init sequence (probe → lease bring-up → verifier self-test → first userland program → report) | implemented-in-v0.1 | Ordinary Python control flow; the QPU (emulator) is probed like any device, never booted *on* | "Pure classical control flow; QPU is enumerated later like any device **[Demonstrated]**" |
| 2 | Interrupt handling / IRQ core | A | Partially — readout *completion* is exercised, but as the synchronous `qmeasure` drain (`QPUScheduler.run_pending()`), the blocking stand-in for a completion IRQ/CQE | specified-only (async submit + `io_uring` CQE completion is in `qsyscall.h`; v0.1 blocks synchronously — design doc §4) | `QLOSRuntime.qmeasure` drives `run_pending()` to completion; sub-µs feed-forward stays below the kernel by design | "Readout-complete events are ordinary device interrupts; sub-µs feed-forward lives in firmware, not the kernel" |
| 3 | Device driver core (PCIe, DMA, sysfs) | A | Emulated stand-in — `emulator/qcpu.py` *is* the device; the calibration sysfs tree is a deterministic MOCK table in the Stage 5 harness; per-lease measurement rings stand in for DMA result buffers | specified-only (the QCX device layer is the single swap seam behind `run_pending()` — design doc §9 future work, **[Theoretical]**) | `QPUScheduler.run_pending()` fronts the device; `Lease.ring` mirrors the hybrid-board DMA result rings | "QPU control electronics are classical peripherals **[Demonstrated]**" |
| 4 | Syscall machinery / VFS plumbing | A | Yes — the four-call ABI runs (`qos/qsyscalls.py`): qset fds, `-EBADF` on unknown fds, `dup()` → `-EPERM` | implemented-in-v0.1 | `QLOSRuntime.qalloc/qexec/qmeasure/qfree` mirror `qsyscall.h` semantically (same names, struct fields, errnos sourced from the `errno` module) | "Classical; quantum resources ride on fd semantics (with `dup`/`mmap` blocked)" |
| 5 | Scheduler (CFS time-slicing → EDF/batch) | B | Yes — deadline-aware FIFO with coherence-budget admission control; run-to-completion, **no preemption ever** (saving quantum state is **[Proven]** forbidden) | implemented-in-v0.1 (deadlines soft in v0.1: misses counted, the job still runs — design doc §5) | `QPUScheduler.submit` (verify → admit → reserve → enqueue) + `run_pending` dispatch; `-ETIME` on budget overrun | "Job-level batch/EDF admission replaces preemption; circuits run-to-completion under coherence deadlines **[Demonstrated]** (QOS)" |
| 6 | Qubit allocator ("buddy" for qubits) | B | Yes — fixed pool, exclusive linear leases, `-EBUSY` on exhaustion, no overcommit ever | implemented-in-v0.1 (emulated pool is homogeneous/all-to-all, so placement is trivially lowest-free-index; real placement is calibration-aware and fidelity-critical **[Demonstrated]**, QOS) | `LeaseManager.allocate/release` over a sorted free list; pool accounting checked by the Stage 5 harness | "Fixed heterogeneous pool, calibration-aware placement, linear-resource accounting; no overcommit" |
| 7 | Virtual memory: translation / naming layer | B | Yes — per-lease virtual→physical qubit tables; isolation and revocation without ever copying state | implemented-in-v0.1 | `Lease.vq_to_pq` (mirror of `struct qlease_desc.vq_to_pq`); revocation = `qfree` (RESET + return to pool) | "Virtual→physical qubit maps are viable and demonstrated; everything *behind* the table changes" |
| 8 | `fork()` for quantum state | D | No — not implemented and not implementable — **[Proven]** no-cloning theorem (Wootters & Zurek 1982) | impossible | The classical context forks; leases are close-on-fork: `QProcess.fork` gives the child NO leases (`QSET_F_CLOFORK` — move semantics, at most one owner) | "No-cloning **[Proven]**; only move (teleport) or re-execute semantics exist" |
| 9 | Copy-on-write | D | No — not implemented and not implementable — **[Proven]** no-cloning theorem: the "copy" branch of the fault handler is physically undefined | impossible | No CoW path exists anywhere in QLOS; lease ownership moves, never copies | "'Copy' branch is physically undefined **[Proven]**" |
| 10 | Swap / demand paging of qubits | D | No — not implemented and not implementable — **[Proven]** serialization = state tomography at Θ(4ⁿ/ε²) destructive shots over copies no-cloning forbids | impossible | `qalloc` fails fast with `-EBUSY`; nothing in QLOS ever blocks waiting for quantum "memory" to page | "Serialization = tomography = Θ(4ⁿ/ε²) destructive measurements over copies that cannot exist **[Proven]**" |
| 11 | Page cache / KSM dedup / snapshots | D | No — not implemented and not implementable — **[Proven]** no-cloning theorem + measurement postulate (all three are copying or non-destructive reading) | impossible | Only classical artifacts (QOBJ files, histograms, lease metadata) are ever cached or copied in this repo | "All are copying or non-destructive reading **[Proven]**" |
| 12 | `ptrace` / core dumps / debuggers on quantum state | D | No — not implemented and not implementable — **[Proven]** measurement postulate (non-destructive inspection has no physical realization) | impossible | `QCPU._debug_statevector()` and `qrun.py --trace` exist in EMULATION ONLY, underscore-named/bannered to mark their unphysicality; nothing kernel-visible uses them (classical results flow only MEASURE → shadow → FMR) | "Non-destructive inspection forbidden by measurement postulate **[Proven]**" |
| 13 | Filesystems (data at rest) | C | Yes — emulated: circuits at rest are ordinary files (`examples/*.qs`, `*.qobj.json`); results are classical histograms; "quantum persistence" = a re-execution contract (store the circuit, re-`qexec` later) | implemented-in-v0.1 | `toolchain/qas.py`/`qdis.py` round-trip (assemble/disassemble law, design doc §6.3); `MeasureResult.counts()` output is plain data | "Store circuits (QASM/QIR) + classical results; 'quantum persistence' emulated as re-execution contracts" |
| 14 | Quantum resource handles in VFS | B | Yes — one-shot destructive `qmeasure` (explicitly NOT `read(2)`-idempotent), `dup()` → `-EPERM`, consumed-lease reuse → `-EPERM`, lifecycle LIVE → CONSUMED → freed | implemented-in-v0.1 (user-space enforcement only; kernel `O_LINEAR` fds remain research-doc open problem #2 **[Speculative]** — deferred, not promised; workflow Risk 5) | qset fds in `QLOSRuntime`; `Lease.state` mirrors `qlease_desc.state` | "One-shot destructive `read`, no `dup`/`mmap`; capability-style fds" |
| 15 | Network stack (classical TCP/IP) | A | Yes, trivially — everything classical in this repo rides the untouched host stack; the repo adds no network code (single node, workflow Risk 8) | specified-only (class A means the existing stack ports *unchanged*; there is nothing for QLOS to implement, and v0.1 models no networking — design doc limitation 8) | none in-repo; the header/design docs record the classical channel as load-bearing | "Required as the classical channel of every quantum protocol **[Proven]** (teleportation needs 2 classical bits/qubit)" |
| 16 | Quantum networking (`AF_QIPC`) | B | **Not modeled in this repo** — quantum networking is excluded entirely (workflow Risk 8) | specified-only (no reference design exists anywhere — research-doc open problem #5 **[Speculative]**; explicitly not promised) | none | "Entanglement generation/consumption with deadlines; QNodeOS shows the shape **[Demonstrated]**" |
| 17 | Packet buffering / retransmit / multicast for qubits | D | No — not implemented and not implementable — **[Proven]** no-cloning theorem (store-and-forward buffering and multicast are cloning) | impossible | none; on real links reliability comes from entanglement distillation, never retransmission | "Store-and-forward and multicast are cloning **[Proven]**" |
| 18 | Security: memory isolation between quantum jobs | B | Partially — lease *namespace* isolation works: leases partition the pool exclusively, and a submitted program cannot name qubits outside its lease (lease-sized re-verification at `qexec`, `-ENOEXEC`). Crosstalk budgeting is NOT modeled | implemented-in-v0.1 (isolation); crosstalk budgeting deferred (the emulator has no crosstalk to budget) | `LeaseManager` exclusive partition + `QCPU.verify` against the real lease at submit (defense in depth, design doc §6.3) | "Physical isolation + crosstalk budgeting replace page-table protection; observation-based auditing impossible" |
| 19 | Timekeeping (clocksource, hrtimers) | A | Partially — `QWAIT` cycle counting and the scheduler's virtual clock (`virtual_now_cycles`) are exercised and reported by the Stage 5 harness; explicitly NOT a timing/coherence model (workflow Risk 3) | implemented-in-v0.1 (as counters/policy arithmetic only, **[Theoretical]**; real gate scheduling is deterministic-time and firmware-enforced **[Demonstrated]**) | `QCPU.qwait` cycle counter; `QPUScheduler.virtual_now_cycles`; `init-report.json` logs both | "Becomes *more* critical: gate scheduling is deterministic-time; ns-precision timers are load-bearing" |
| 20 | Power management | B | Not modeled — the noiseless statevector has no QEC duty cycle to account | specified-only (idle logical qubits burn active error-correction cycles **[Demonstrated]** (Willow-class QEC); pool *accounting* for that is research-doc open problem #4 **[Speculative]** — deferred, not promised) | none | "Logical qubits consume active error-correction duty cycle even when 'idle' **[Demonstrated]**" |
| 21 | Console / tty / userspace ABI | A | Yes — users see job APIs and classical text, never qubits: `qrun.py` prints counts histograms; the init harness logs printk-style; `qas`/`qdis` are ordinary CLI filters | implemented-in-v0.1 | `examples/qrun.py`, `toolchain/qas.py`/`qdis.py` CLIs; classical stdout only | "Untouched; users see job APIs, not qubits" |

## Tally and reading guide

- **A: 7 rows** (1–4, 15, 19, 21) — directly portable because they were classical all along;
  in this repo they are exercised by the Python harness where there is anything to exercise.
- **B: 7 rows** (5–7, 14, 16, 18, 20) — quantum-aware rewrites; v0.1 implements the lease
  manager, EDF-style admission, naming layer, capability fds, and lease isolation, and defers
  `AF_QIPC` (Risk 8) and QEC-duty-cycle power accounting.
- **C: 1 row** (13) — the emulation layer: circuits and results as ordinary files plus
  re-execution contracts, fully implemented by the toolchain.
- **D: 6 rows** (8–12, 17) — the short but absolute list: exactly the set of features whose
  semantics are copying or non-destructive observation. Every D-row names its **[Proven]**
  law (no-cloning theorem; measurement postulate; the Θ(4ⁿ/ε²) tomography corollary). These
  are not engineering gaps — they are undefined operations on quantum state, and no QLOS
  version will ever implement them.

**[Speculative] hygiene** (workflow Stage 5 acceptance criterion): no row above promises a
capability the research doc tags **[Speculative]**. Every [Speculative] mention (kernel
`O_LINEAR` fds, `AF_QIPC` design, QEC duty-cycle accounting, QCX hardware) marks an exclusion
or deferral, never a commitment. Assertions in the Stage 5 harness pin only the
**[Demonstrated]** Nighthawk figure of 5,000 reliable two-qubit gates (workflow Risk 7).
