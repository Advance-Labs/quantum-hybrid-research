# `arch/quantum/` Port Notes — Stage 3 Paper Port

**Document:** quantum-linux/kernel-patches/arch-quantum-notes.md
**Status:** Stage 3 deliverable (paper port — documentation and pseudocode only)
**Sources of truth:** [research doc](../../docs/research/02-quantum-linux.md) · [workflow doc, Stage 3](../../docs/workflows/02-linux-workflow.md)
**Reference tree:** Linux 6.12 LTS (read-only audit reference; **not** vendored into this repo)

---

## 1. Framing (binding)

This document is the product of the Stage 3 *literal-port thought experiment*: what would an
`arch/quantum/` target in the Linux source tree actually require, directory by directory, measured
against `arch/x86`? The research doc's verdict is binding here: a literal port of Linux *onto*
qubits is infeasible in principle — a corollary of the **[Proven]** no-cloning theorem
(Wootters & Zurek, 1982) and the **[Proven]** measurement postulate — while Linux as the classical
*control plane* of a QPU is **[Demonstrated]** practice on every deployed system (QOS, OSDI '25;
QNodeOS, Nature 2025; every IBM/Google/IonQ control rack).

Accordingly:

- **No deliverable in this directory claims or implies a bootable quantum kernel.** Everything in
  `arch-quantum/` is annotated pseudocode whose purpose is to pinpoint *where* each subsystem
  breaks, not to build.
- Every component verdict below is keyed to the research doc's feasibility classes:
  **(A)** directly portable · **(B)** quantum-aware rewrite · **(C)** classical emulation layer ·
  **(D)** fundamentally incompatible.
- Running classical kernel control flow on qubits is not merely hard, it is strictly worse than
  pointless: quantum speedups are algorithm-specific (Grover's O(√N) oracle queries
  **[Proven]**, optimal per the BBBV Ω(√N) bound **[Proven]**), and branch-heavy, I/O-bound,
  irreversibly stateful kernel code would pay the full QEC overhead — ~10³ physical qubits per
  logical qubit on current surface-code trendlines **[Demonstrated]** — to run *slower* than a
  commodity core (research doc, "Why running kernel logic itself on qubits gains nothing").

---

## 2. Directory-by-directory: `arch/x86` vs. a hypothetical `arch/quantum`

Each subsection covers: what the x86 directory does, what QISA-K (see
`../isa-spec/QISA-v0.1.yaml`, Stage 1) can and cannot express, and the A/B/C/D verdict.

### 2.1 `arch/x86/boot/` — boot code

**What x86 does:** real-mode entry, BIOS/EFI handoff, kernel decompression
(`boot/compressed/`), command-line parsing, jump to protected/long mode.

**What QISA-K can express:** nothing relevant. The QISA-K register model (research doc, QISA
table) has no load/store, no pointer arithmetic, and no addressable memory — quantum registers
`q0 … qN-1` name physical resources, not value containers. There is no place to *put* a kernel
image: an n-qubit register cannot store classical code, and reading any of it back would be a
destructive measurement **[Proven]**.

**Verdict: Class A — on the classical host, unchanged.** Boot/init is pure classical control
flow; the QPU is enumerated later like any device, **[Demonstrated]** on all real systems
(research doc classification table, "Boot / init (start_kernel)" row). There is no
`arch/quantum/boot/`; there is the existing x86/ARM boot path of the host, full stop.

### 2.2 `arch/x86/Kconfig` — architecture configuration

**What x86 does:** declares the architecture's capabilities to the rest of the kernel via
`select`/`depends on`: `CONFIG_MMU`, `HAVE_ARCH_TRACEHOOK`, `ARCH_SUPPORTS_KEXEC`,
`HAVE_KPROBES`, `ARCH_HIBERNATION_POSSIBLE`, SMP topology, …

**What a Kconfig for quantum state would have to say:** the honest exercise is enlightening
because Kconfig *is* a capability declaration, and most capability symbols are physically
unsatisfiable for quantum state:

| Kconfig symbol (x86) | Satisfiable for quantum state? | Why (research-doc class) |
|---|---|---|
| `CONFIG_MMU` | No — naming layer only | Translation/naming is viable (B); demand paging, overcommit, dirty tracking behind it are D **[Proven]** (no-cloning; measurement postulate) |
| `ARCH_HIBERNATION_POSSIBLE` | No | Hibernate = serialize state = tomography Θ(4^n/ε²) over copies that cannot exist (D) **[Proven]** |
| `HAVE_ARCH_TRACEHOOK` (`ptrace`) | No | Non-destructive inspection forbidden by measurement postulate (D) **[Proven]** |
| `ARCH_SUPPORTS_KEXEC` | No | Re-execution of a *circuit* from classical inputs exists (C), but kexec'ing live state is copying (D) **[Proven]** |
| `CONFIG_SMP` | Reinterpreted | Spatial multiplexing of disjoint qubit regions is real and **[Demonstrated]** (QOS, up to 9.6× utilization), but it is job placement (B), not symmetric multiprocessing |
| `CONFIG_SWAP` | No | Swap is **[Proven]** impossible; "no overcommit, ever" is the `qalloc` contract (research doc errno table) |

**Verdict:** the only buildable `Kconfig` is the one in `arch-quantum/Kconfig.notes` — a
pseudocode artifact in which nearly every `HAVE_*` symbol carries a comment naming the theorem
that forbids it. The host kernel's real Kconfig change is one line: a `CONFIG_QPU` driver
subsystem (Class A machinery, see §5).

### 2.3 `arch/x86/kernel/head_64.S` — the `head.S` equivalent

**What x86 does:** earliest kernel-mode code — set up initial page tables, clear BSS, load GDT/IDT,
establish a stack, jump to `start_kernel()` in C.

**What QISA-K can express:** a narrow, suggestive sliver. The closest analogue of "bring the
machine to a known state" is a `RESET` sweep over the leased register (active |0⟩ preparation,
non-unitary) followed by `QWAIT` cycle alignment — exactly the preamble of the research doc's
Bell-pair listing. That is where the analogy ends:

- **No stack.** A stack is mutable, copyable, addressable memory. Qubits are linear (affine)
  resources — usable at most once along any data path, never duplicated, consumed by
  `MEASURE`/`RESET` (research doc, design consequence in the memory-model section).
- **No "jump to C".** There is no instruction fetch from quantum memory; QISA-K programs are
  circuits compiled ahead of time and run to completion inside the coherence window —
  µs–ms on superconducting hardware, seconds trapped-ion **[Demonstrated]**.
- **No early console, no BSS, no GDT.** All of that state is classical by definition; in the
  hybrid architecture it lives on the host and never left.

**Verdict: Class A (host) / pseudocode-only (`head.qS`).** The `arch-quantum/head.qS` sketch
exists to show the *largest expressible prefix* of a boot sequence (RESET sweep + QWAIT) and the
exact instruction at which the port hits the class-D wall (first required load/store).

### 2.4 `arch/x86/kernel/irq.c`, `apic/` — interrupt handling

**What x86 does:** vector management, APIC programming, IRQ entry/exit, softirq plumbing.

**Quantum reality:** readout-complete events from the QPU control electronics are *ordinary
device interrupts* on the host — the completion path returns classical shot data via ordinary
DMA (research doc, device-driver subsystem analysis). The one thing the IRQ core must **not** be
asked to do is feed-forward: measure → decide → apply-gate must complete inside the coherence
window, demanding sub-microsecond classical latency. Linux interrupt latency is µs-scale with
unbounded tails; the inner loop therefore lives in FPGA/ASIC firmware below the kernel —
the QNodeOS CNPU/QNPU split **[Demonstrated]** exactly this layering.

**Verdict: Class A.** "Readout-complete events are ordinary device interrupts; sub-µs
feed-forward lives in firmware, not the kernel" (research doc classification table, verbatim).

### 2.5 `arch/x86/mm/` — memory management

**What x86 does:** page-table formats (`pgtable.h`), fault handling (`fault.c`), TLB management,
NUMA, hugepages — the machinery beneath `fork()`, CoW, swap, and the page cache.

**This is the class-D wall.** All four Linux memory invariants fail for quantum state
(research doc, "The quantum memory model — where the kernel breaks"):

| Invariant | Breaks because | Status | First trap point in 6.12 (annotated in `arch-quantum/` pseudocode) |
|---|---|---|---|
| State can be copied | No-cloning theorem | **[Proven]** | `kernel/fork.c: copy_process() → dup_mm() → mm/memory.c: copy_page_range()` — the first page-copying line has no physical meaning for a quantum page |
| Copy-on-write | The "duplicate" branch is physically undefined — CoW collapses to move-on-touch | **[Proven]** | `mm/memory.c: do_wp_page()` — the write-fault duplicate cannot exist |
| State can be serialized (swap) | Serialization = tomography, Θ(4^n/ε²) destructive measurements over copies that cannot exist | **[Proven]** | `mm/vmscan.c → mm/page_io.c: swap_writepage()` |
| State can be read non-destructively | Measurement postulate (projective collapse) | **[Proven]** | `kernel/ptrace.c: ptrace_readdata() → access_process_vm()`; also dirty/accessed bits in `pgtable.h` |
| State persists while descheduled | Decoherence, F(t) ≈ e^(−t/T2); QEC logical qubits burn *active* syndrome cycles | **[Demonstrated]** | no single line — it is the premise of the entire LRU/reclaim design |

**What survives (Class B):** exactly the *naming* layer — a per-process table mapping virtual
qubit handles to physical qubits gives relocation, isolation, and revocation without ever copying
state, and is **[Demonstrated]** by QOS's placement layer. "Virtual memory minus paging is a
capability system" (research doc) — which is why Stage 4's `qsyscall.h` is capability-shaped.
Compaction survives only as SWAP-gate/teleportation *migration* at O(√N) SWAP depth per logical
move on an N-qubit 2D lattice **[Proven]** (graph-distance lower bound).

**Verdict: Class D for everything behind the translation table** (`fork()` D, CoW D,
swap/demand paging D, page cache/KSM/snapshots D, `ptrace`/core dumps D — zero reclassifications
from the research doc's table); **Class B for translation/naming** (the qubit allocator is a
fixed, small, heterogeneous, calibration-aware pool — closer to CPU-affinity-aware hugepage
reservation than to page allocation).

### 2.6 `arch/x86/entry/` — syscall entry (`entry_64.S`, `syscalls/`)

**What x86 does:** `syscall` instruction entry, register save/restore, the syscall table,
signal-delivery glue.

**Quantum reality:** syscall machinery is pure classical control flow and ports unchanged
(Class A: "Syscall machinery / VFS plumbing — classical; quantum resources ride on fd semantics",
research doc classification table). The change is *additive*: four new entries —
`QALLOC` / `QEXEC` / `QMEASURE` / `QFREE` — realistically implemented as an `ioctl`/`io_uring`
family on a `/dev/qpu0` character device (research doc, "Syscall additions"). The only semantic
twist the entry layer must enforce is the linear-capability discipline on qubit-set fds:
`dup()` → `-EPERM`, close-on-fork forced (move semantics, at most one owner), `mmap()` rejected —
because duplication of the underlying resource is **[Proven]** physically undefined.
See `qsyscall.h` in this directory for the full contract.

**Verdict: Class A machinery + Class B additions.**

---

## 3. The five most-portable subsystems (workflow Stage 3, step 2)

Selected per the research doc's class-A/B rows. LOC and dependency fan-out are order-of-magnitude
figures (≈) from the Linux 6.12 LTS reference tree audit; they exist to size the *classical*
skeleton, not to promise a build.

| # | Subsystem | x86/6.12 anchor | ≈ LOC | Dependency fan-out | Class & why it ports |
|---|---|---|---|---|---|
| 1 | Minimal arch layer (`head*.S` analogue) | `arch/x86/kernel/head_64.S` + `head64.c` | ≈ 1.3 k | Low — memory map, early params | **A** (host) — earliest code is classical by construction; the QISA-K-expressible sliver (RESET sweep, QWAIT) is sketched as pseudocode in `arch-quantum/head.qS` |
| 2 | `init/main.c` (`start_kernel`) | `init/main.c` | ≈ 1.6 k | High call-out, low call-in — it is the orchestrator | **A** — pure classical control flow; the QPU is enumerated later like any device **[Demonstrated]** |
| 3 | `printk` | `kernel/printk/` | ≈ 5 k | Very low — ringbuffer + console drivers | **A** — classical byte stream; quantum job results land as plain files/buffers; nothing here ever touches quantum state |
| 4 | Run-to-completion scheduler stub | new (replaces the CFS entity for quantum jobs); cf. `kernel/sched/` ≈ 30 k for contrast | ≈ 0.5 k (stub) | Low — workqueue + deadline class in a device driver | **B** — EDF/batch *admission* replaces CFS time-slicing because preemption of a running circuit is **[Proven]** impossible (context save = copying state, forbidden by no-cloning; inspection = measurement). Spatial/temporal multiplexing is **[Demonstrated]** (QOS: up to 9.6× utilization at 1–3% average fidelity cost). A quantum job is a GPU-kernel-launch analogue, not a thread |
| 5 | Timekeeping | `kernel/time/` | ≈ 25 k | Medium — clocksource, hrtimers, broadcast | **A, and *more* critical** — gate scheduling is deterministic-time; ns-precision timers are load-bearing (research doc classification table). `QWAIT` semantics and EDF coherence deadlines both hang off this subsystem |

Why these five: between them they cover the entire surviving skeleton of a kernel
bring-up — get to C (`head`), orchestrate (`start_kernel`), observe (`printk`), admit work
(scheduler stub), and meter time (timekeeping) — and none of them requires a single operation
that quantum mechanics forbids, *provided they run on the classical host*.

---

## 4. What stays on the classical co-processor (hybrid architecture)

Per the research doc's proposed architecture, the answer is: **the entire kernel.** Linux runs
unmodified on the classical host CPU; quantum work is dispatched across a narrow driver boundary,
exactly as GPUs are managed today, plus hard-real-time firmware below the driver for feed-forward:

1. **`qpu_core` (kernel, soft real-time):** lease accounting, job queue with EDF admission by
   coherence deadline, calibration `sysfs` tree (per-qubit T1/T2/error rates), multiplexing
   policy (spatial placement of concurrent leases with crosstalk budgets).
2. **`qpu_hw` (kernel, per-vendor):** translates QIR to the vendor QISA (eQASM-class), DMAs pulse
   schedules to the control stack, fields completion IRQs.
3. **Control firmware (FPGA/ASIC, hard real-time, below Linux):** µs-scale pulse playback,
   readout discrimination, feed-forward branching. The kernel never sits in this loop.

Classical and load-bearing forever (not NISQ-era stopgaps): the classical TCP/IP stack (every
quantum protocol needs a paired classical channel — teleportation costs 2 classical bits per
qubit **[Proven]**), the VFS (circuits and shot histograms are ordinary files; Class C
"persistence" is a stored circuit plus a re-execution contract), and all of mm/sched/drivers for
classical state. The hybrid split is the asymptotically correct division of labor, not a
temporary compromise **[Theoretical]** (research doc, reversible-execution analysis). Pool
sizing context: 2026 hardware exposes 10²–10³ physical qubits (Nighthawk 120 qubits/module,
5,000 reliable two-qubit gates **[Demonstrated]**; IonQ Forte Enterprise 36 qubits at 99.6% 2Q
fidelity **[Demonstrated]**) — a small-device allocation problem, far below where sophisticated
mm machinery would pay for itself.

---

## 5. Component map: `arch/x86` → quantum equivalent / elimination

One row per component an arch port would touch. **Class** values are taken from the research
doc's feasibility classification table; rows marked *(derived)* apply that table's nearest row to
an arch-specific file.

| `arch/x86` component | Quantum equivalent / elimination | Class | Rationale |
|---|---|---|---|
| `boot/` (real-mode, decompression) | Eliminated — host boots classically; QPU enumerated later as a device | A | Pure classical control flow **[Demonstrated]** on all real systems |
| `Kconfig` | `Kconfig.notes` pseudocode; host gains a `CONFIG_QPU` driver symbol | A (host) / D (capability symbols for quantum state) | Most `HAVE_*` symbols are theorem-blocked — see §2.2 |
| `kernel/head_64.S` | `head.qS` pseudocode: RESET sweep + QWAIT prefix, then class-D wall at first load/store | A (host) | No instruction fetch from quantum memory; circuits are compiled ahead of time, run to completion |
| `kernel/setup.c` | `setup.c` pseudocode: "CPU" probe = qubit count + per-qubit T1/T2 from calibration table (`sysfs` in the real driver) | B *(derived: qubit allocator row)* | Calibration as first-class state **[Demonstrated]** (QOS hardware-aware compilation); memory is non-fungible — per-qubit drift makes placement fidelity-critical **[Demonstrated]** |
| `entry/entry_64.S` + syscall table | Unchanged machinery + `QALLOC`/`QEXEC`/`QMEASURE`/`QFREE` family (`/dev/qpu0` ioctl in practice) | A (machinery) / B (additions) | Classical; quantum resources ride on fd semantics with `dup`/`mmap` blocked **[Proven]** undefined otherwise |
| `kernel/irq.c`, `apic/` | Unchanged — readout-complete = device IRQ; feed-forward pushed to firmware | A | Sub-µs feed-forward cannot meet deadlines through Linux IRQ paths **[Demonstrated]** (eQASM; QNodeOS QNPU) |
| `mm/pgtable.h`, page-table walkers | Per-process virtual→physical *qubit* table only (naming/isolation/revocation) | B | Translation survives **[Demonstrated]** (QOS placement); dirty/accessed bits eliminated — they require observation **[Proven]** |
| `mm/fault.c` (demand paging, CoW faults) | Eliminated | D | CoW's duplicate branch is physically undefined **[Proven]**; demand paging needs copy **[Proven]** |
| swap path (`swap_writepage` & friends) | Eliminated — no overcommit, ever; `qalloc` fails `-EBUSY` at pool exhaustion | D | Serialization = tomography Θ(4^n/ε²) over copies that cannot exist **[Proven]** |
| Page cache / KSM / snapshots glue | Eliminated | D | All are copying or non-destructive reading **[Proven]** |
| `kernel/process.c` (`fork`, context switch of register state) | `fork()` of quantum pages eliminated; lease fds are close-on-fork (move semantics). "Suspend/resume" emulated as checkpoint-by-reexecution | D (`fork` for quantum state) / C (re-execution emulation) | No-cloning **[Proven]**; only move (teleport — destroys source, **[Proven]**/**[Demonstrated]**) or re-execute semantics exist |
| `ptrace` arch hooks, core-dump writers | Eliminated for quantum state; classical shadow registers remain fully debuggable | D | Measurement postulate forbids non-destructive inspection **[Proven]** |
| `kernel/tsc.c`, clocksource glue | Ported and promoted — deterministic gate timing, EDF coherence deadlines | A | Timekeeping becomes *more* critical (research doc table) |
| `pci/`, DMA, device core | Unchanged — QPU control electronics are classical PCIe peripherals | A | **[Demonstrated]** on every IBM/Google/IonQ control rack |
| `power/` (suspend, hibernate) | Hibernate of quantum state eliminated; PM rewritten for QEC duty-cycle accounting — "idle" logical qubits burn active syndrome cycles | B | Willow-class QEC: distance-7 logical qubit at 0.143% error/cycle requires continuous cycles **[Demonstrated]**; idle quantum memory is a running process |
| `kvm/` (virtualization, VM snapshots) | VM snapshot/migration of quantum state eliminated *(derived: snapshots row)*; classical VMs untouched | D (quantum state) | Snapshots are copying **[Proven]** |
| Console / tty glue | Unchanged | A | Users see job APIs, not qubits |

---

## 6. Changes vs. x86 — file-level summary (workflow Stage 3, step 5)

One row per file a real arch port would touch, with the honest outcome:

| File (x86 anchor) | Action in `arch/quantum` | Outcome |
|---|---|---|
| `Kconfig` | Write `Kconfig.notes` (pseudocode) | Most capability symbols unsatisfiable at theorem level (§2.2); host needs only a `CONFIG_QPU` driver symbol |
| `head.S` (`head_64.S`) | Write `head.qS` (QISA-K pseudocode) | RESET-sweep + QWAIT prefix expressible; wall at first load/store — no addressable memory, no instruction fetch |
| `setup.c` | Write `setup.c` (C pseudocode) | "CPU" probe becomes qubit count + T1/T2 calibration table read; feeds the class-B allocator |
| `entry.S` | No quantum equivalent; host gains 4 syscalls / one ioctl family | See `qsyscall.h`; linear-capability enforcement (`dup` → `-EPERM`, close-on-fork) is the only new semantic |
| `pgtable.h` | Reduced to a virtual→physical qubit map type | Naming survives (B); every bit of paging metadata behind it is D **[Proven]** |
| `fault.c` | Not written | Demand paging / CoW are D **[Proven]** — annotated as the first-line trap in `setup.c` pseudocode |
| `irq.c` / vector tables | Unchanged host code | Readout IRQs are ordinary; feed-forward in firmware (A) |
| `time.c` / clocksource | Unchanged host code, tighter constraints | A, more critical — deterministic gate timing |
| `process.c` (switch_to) | Not written for quantum state | Context save of a circuit = copying **[Proven]**; run-to-completion under EDF instead (B) |
| `ptrace.c` arch hooks | Not written | D **[Proven]** — measurement postulate |
| `Makefile` | Trivial (pseudocode tree is not built) | Stage 3 acceptance: no buildable kernel claimed |

---

## 7. Closing recommendation

The audit confirms, with zero reclassifications, the research doc's classification table: the
majority of kernel *code* is class A/B — because the majority of a quantum computer is
classical — and the class-D list is short but absolute: exactly the set of features whose
semantics are copying or non-destructive observation (`fork`, CoW, swap/demand paging, page
cache/KSM/snapshots, `ptrace`/core dumps), each blocked by a **[Proven]** physical law, plus
descheduled persistence blocked by decoherence **[Demonstrated]**.

Effort should therefore be redirected, per the research doc's verdict ("Hybrid control-plane
Linux — feasible, demonstrated in adjacent systems, and the only architecture worth building
**[Demonstrated]**"), to the Stage 4 hybrid dispatch interface: the four-call
`QALLOC`/`QEXEC`/`QMEASURE`/`QFREE` family with capability-style leases, EDF circuit admission,
and calibration-aware placement — specified in [`qsyscall.h`](qsyscall.h) in this directory and
exercised against the Stage 2 emulator by `emulator/qsyscall_shim.py`. The open, *classical*
research directions this unlocks (mainline `qpu` subsystem; kernel-enforced linear-typed fds;
EDF under calibration drift; logical-qubit pool accounting) are enumerated in the research doc's
"Open problems worth pursuing" and remain **[Speculative]**–**[Theoretical]** as tagged there.
