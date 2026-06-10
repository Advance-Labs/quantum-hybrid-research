# QuantumLinux — Porting the Linux Kernel to a Quantum Architecture: Feasibility Study

**Document:** docs/research/02-quantum-linux.md
**Status:** Research / feasibility analysis
**Last updated:** June 2026

---

## Abstract

This document analyzes whether the Linux kernel — or any general-purpose operating system — can be "ported" to quantum hardware, and concludes that a literal port is impossible — a direct corollary of **[Proven]** theorems of quantum mechanics — while a hybrid architecture is **[Demonstrated]** practical. The analysis proceeds in four steps. First, we map the three dominant quantum execution models (gate-based, adiabatic, measurement-based) onto classical OS abstractions and identify the fundamental mismatches. Second, we sketch a theoretical Quantum Instruction Set Architecture (QISA) the kernel could target, drawing on real designs (eQASM, OpenQASM 3, QIR), and show that the quantum memory model violates core kernel invariants: the no-cloning theorem **[Proven]** (Wootters & Zurek, 1982) makes `fork()`, copy-on-write, swap, and page-cache semantics unimplementable for quantum state. Third, we audit each major kernel subsystem (scheduler, memory manager, VFS, network stack, device drivers) and classify every component as portable, rewritable, emulatable, or fundamentally incompatible. Fourth, we survey real quantum OS research as of mid-2026 — QOS (OSDI '25), QNodeOS (Nature, 2025), Quingo, QuNetSim, and the Microsoft Q#/QIR runtime stack — all of which converge on the same architecture we propose: a classical kernel orchestrating a quantum co-processor through a narrow, capability-style syscall interface (`QALLOC`/`QEXEC`/`QMEASURE`/`QFREE`). The honest verdict: "QuantumLinux" as a kernel *running on* qubits is incoherent under known physics — a corollary of the **[Proven]** no-cloning theorem and measurement postulate; Linux as the *control plane* for QPUs is the only viable design, and it is already how every deployed quantum computer works **[Demonstrated]**.

---

## Quantum Execution Models vs. Classical OS Concepts

A classical OS abstracts a von Neumann machine: a CPU that fetches instructions from mutable, copyable, addressable memory, with interrupts and preemption as the concurrency primitives. None of the three quantum execution models satisfies these assumptions.

### Gate-based (circuit model)

The dominant model — used by IBM, Google, and IonQ hardware — applies a sequence of unitary operators from a universal gate set to a register of qubits, followed by measurement. Universality of finite gate sets (e.g., {H, T, CNOT}) is **[Proven]** via the Solovay–Kitaev theorem, with approximation overhead O(log^c(1/ε)) gates to reach precision ε (c ≈ 2–4 depending on construction). The defining OS-relevant property: a program is a *circuit*, compiled ahead of time, executed within the coherence window. On 2026 hardware that window is microseconds-to-milliseconds (superconducting) or seconds (trapped-ion) **[Demonstrated]** — far shorter than a Linux scheduler tick (1–10 ms) in the superconducting case.

### Adiabatic / annealing

Computation by slow evolution of a Hamiltonian H(t) = (1−t/T)·H_init + (t/T)·H_final, where the answer is the ground state of H_final (Farhi et al., arXiv:quant-ph/0001106) **[Theoretical]** for general-purpose use; **[Demonstrated]** for optimization sampling on annealers. Adiabatic quantum computation is polynomially equivalent to the circuit model **[Proven]** (Aharonov et al., SIAM J. Comput. 2007). Required runtime scales as O(1/g_min²), where g_min is the minimum spectral gap — generally unknown and possibly exponentially small. There is no instruction stream at all: the "program" is an energy landscape. Preemption is physically meaningless; interrupting the evolution destroys the computation.

### Measurement-based (MBQC / one-way)

Prepare a large entangled cluster state, then drive computation purely by adaptive single-qubit measurements, where each measurement basis depends on prior outcomes (Raussendorf & Briegel, PRL 86, 5188, 2001) **[Proven]** equivalent in power to the circuit model. The resource is *consumed* as it is used — the cluster state is destroyed by the measurements that constitute the program. This is the closest analogue to "dataflow" execution, but with strictly single-use memory.

### Mapping table

| Quantum execution model | Closest OS concept analogue | Fundamental mismatch |
|---|---|---|
| Gate-based circuit | A process: compiled program + register state | No mid-execution inspection: reading state = measurement = destructive collapse **[Proven]**. No preemption: context save requires copying state, forbidden by no-cloning **[Proven]**. Coherence deadline (µs–ms) shorter than scheduler quantum **[Demonstrated]** |
| Gate-based shot loop | A thread pool re-running the same job | Shots are statistically independent trials, not cooperating threads; no shared mutable memory between them — IPC between shots is physically impossible within one coherence window |
| Adiabatic evolution | A batch job / `nice -19` background task | No instruction pointer, no syscalls, no progress signal; runtime bound O(1/g_min²) is uncomputable in general **[Theoretical]**; cannot be checkpointed or resumed |
| MBQC cluster state | One-shot dataflow graph; `O_TMPFILE` memory | Memory is consumed by execution; "read" and "execute" are the same destructive operation; adaptive feed-forward requires classical control with latency below the decoherence time **[Demonstrated]** in QNodeOS-class systems |
| Measurement / readout | Blocking `read(2)` on a device | Returns one classical sample from a distribution, not the state itself; extracting an n-qubit amplitude vector requires O(4^n / ε²) shots of state tomography **[Proven]** |

The shared conclusion across all three models: the OS notions of *transparent state inspection*, *state copying*, and *time-sliced preemption* have no physical realization for quantum data. Any "QuantumLinux" must therefore keep all kernel state classical.

### Why running kernel logic itself on qubits gains nothing

It is worth closing one tempting loophole explicitly. Quantum computers can simulate any classical computation reversibly (via Toffoli-gate constructions) **[Proven]**, so one *could* in principle encode kernel control flow as a quantum circuit. But quantum speedups are algorithm-specific, not execution-mode-generic: Grover gives O(√N) oracle queries against the classical Θ(N) for unstructured search **[Proven]**, and this is optimal — the BBBV lower bound shows Ω(√N) queries are required **[Proven]** — while Shor's super-polynomial advantage applies to period-finding structure absent from scheduler queues and inode lookups. Kernel workloads are branch-heavy, I/O-bound, and irreversibly stateful; executing them on fault-tolerant qubits would pay the full QEC overhead (currently ~10³ physical qubits per logical qubit at useful error rates on surface codes **[Demonstrated]** trendlines from Willow-class devices) to run *slower* than a commodity core. Reversibility also forces garbage accumulation: uncomputing intermediate state to keep evolution unitary costs extra time or space (Bennett's reversible-computation tradeoffs), with zero offsetting algorithmic gain for control-plane code. The hybrid split is not a temporary NISQ-era compromise; it is the asymptotically correct division of labor **[Theoretical]**.

---

## Quantum ISA Design: a QISA the Kernel Could Target

We sketch **QISA-K**, a theoretical kernel-facing instruction set in the lineage of real designs: eQASM, the first executable QISA validated on superconducting hardware (Fu et al., HPCA 2019, arXiv:1808.02449) **[Demonstrated]**; OpenQASM 3, which formalizes the two timescales of quantum-classical interaction — real-time (within coherence) and near-time (Cross et al., ACM TQC 2022, arXiv:2104.14722); and QIR, the LLVM-based intermediate representation governed by the Linux Foundation's QIR Alliance.

### Register model

- **Quantum registers:** `q0 … qN-1`. Physical qubit identifiers. Not addressable memory: no load/store, no pointer arithmetic, no aliasing. A "register" here names a physical resource, not a value container.
- **Classical shadow registers:** `c0 … cN-1`. One-bit (or wider, for multi-shot counters) classical registers that receive measurement outcomes. These are ordinary memory and obey ordinary semantics. All kernel-visible state lives here.
- **Convention:** every `MEASURE qi -> ci` pairs qubit *i* with shadow register *i* by default; the shadow file is the *only* part of the machine state that can be context-switched, copied, or swapped.

### Instruction table

| Opcode | Operands | Semantics | Unitary? | Encoding sketch (32-bit) |
|---|---|---|---|---|
| `H` | `q` | Hadamard: basis superposition | Yes | `[8b op][2b fmt][14b q][8b rsvd]` |
| `X` / `Y` / `Z` | `q` | Pauli flips/phase | Yes | same single-qubit format |
| `S` / `T` | `q` | Phase π/2, π/4 (T is the non-Clifford resource) | Yes | same |
| `RX(θ)` / `RY(θ)` / `RZ(θ)` | `q, θ` | Continuous rotation; θ as 16-bit fixed-point or LUT index, after eQASM | Yes | `[8b op][14b q][10b θ-idx]` |
| `CNOT` | `qc, qt` | Controlled-X; entangling | Yes | `[8b op][12b qc][12b qt]` |
| `CZ` | `qc, qt` | Controlled-Z (native on most superconducting lattices) | Yes | same two-qubit format |
| `MEASURE` | `q -> c` | Project to Z basis; write outcome to shadow register; destroys superposition | **No** | `[8b op][12b q][12b c]` |
| `RESET` | `q` | Active reset to \|0⟩ (measure + conditional X) | **No** | single-qubit format |
| `FMR` | `c -> GPR` | Fetch measurement result into classical pipeline (after eQASM's `FMR`) | n/a | classical format |
| `QWAIT` | `cycles` | Deterministic timing barrier (gate scheduling is time-critical) | n/a | `[8b op][24b cycles]` |

Notes on realism: per IBM's deployed stack, the Nighthawk processor (launched November 2025) exposes 120 qubits on a square lattice and supports circuits with 5,000 reliable two-qubit gates **[Demonstrated]**, with ~7,500 targeted by end of 2026 **[Speculative]** (roadmap). IonQ's trapped-ion systems expose all-to-all connectivity at 99.6% two-qubit fidelity on the shipping 36-qubit Forte Enterprise **[Demonstrated]**, with ~99.9% demonstrated on barium two-ion chains and specified for ~100-qubit Tempo-class hardware. A real QISA-K backend would also need SIMD-style "same gate, many qubits" formats and VLIW timing slots, exactly as eQASM found **[Demonstrated]**.

### Example: Bell pair with feed-forward in QISA-K

The following listing prepares a Bell pair, measures one half, and conditionally corrects the other — the inner loop of teleportation, and the minimal program exercising every semantic class in the ISA (unitary, non-unitary, classical transfer, timing):

```asm
; lease assumed: q0, q1 mapped by the kernel's virtual->physical qubit table
        RESET   q0              ; non-unitary: active |0> preparation
        RESET   q1
        QWAIT   12              ; deterministic cycle alignment (eQASM-style)
        H       q0              ; q0 -> (|0> + |1>)/sqrt(2)
        CNOT    q0, q1          ; entangle: (|00> + |11>)/sqrt(2)
        MEASURE q0 -> c0        ; destructive: collapses the pair
        FMR     c0 -> r1        ; shadow register into classical pipeline
        BRN     r1, .skip       ; classical branch on outcome (real-time path)
        X       q1              ; conditional correction
.skip:
        MEASURE q1 -> c1
        ; c0, c1 are the ONLY kernel-visible artifacts of this program
```

Two properties matter for the kernel. First, the branch at `BRN` must resolve within the coherence window of `q1` — on superconducting hardware this is why feed-forward executes in control firmware, not in any OS code path **[Demonstrated]** (eQASM; QNodeOS's real-time QNPU). Second, after line `MEASURE q0 -> c0`, the instruction `H q0` would be a *use-after-measure* fault unless preceded by `RESET` — the verifier described in the syscall section rejects such programs statically, the quantum analogue of W^X enforcement.

### The quantum memory model — where the kernel breaks

This is the core of the feasibility question. The Linux memory manager is built on four invariants, every one of which fails for quantum state.

**Invariant 1: memory can be copied.** The no-cloning theorem **[Proven]** (Wootters & Zurek, Nature 299, 802–803, 1982): there is no unitary U such that U(|ψ⟩⊗|0⟩) = |ψ⟩⊗|ψ⟩ for arbitrary unknown |ψ⟩. The proof is two lines of linearity and holds for all quantum systems. Consequences:

- **`fork(2)` is unimplementable for quantum pages.** `fork()` semantically duplicates the address space. For a process holding live qubits in superposition, the child's copy cannot exist. The only physically allowed options are (a) *move* semantics — parent loses the qubits (this is what quantum teleportation provides: state transfer that necessarily destroys the original, Bennett et al., PRL 70, 1895, 1993 **[Proven]**, **[Demonstrated]** on hardware) — or (b) re-execution: re-run the preparation circuit from classical inputs to produce a fresh, statistically identical but physically distinct state. Re-execution costs the full circuit depth again and is only valid if the preparation was deterministic from classical data.
- **Copy-on-write collapses to move-on-touch.** CoW's premise is that a cheap shared mapping can be silently duplicated at first write. With qubits, the "duplicate" branch does not exist; the page fault handler would have to either steal the state from the other mapping (breaking the sharing contract) or destroy it. CoW for quantum memory is not "expensive" — it is **[Proven]** undefined.
- **Swap is impossible.** Swapping serializes a page to disk and restores it later. Serializing an unknown n-qubit state means learning its 2^n complex amplitudes, which requires full state tomography: Θ(4^n/ε²) destructive measurements over identically prepared copies — copies which no-cloning forbids us from making from the single live instance **[Proven]**. A qubit can be *moved* (teleported, at the cost of one Bell pair and 2 classical bits per qubit, destroying the source) but never *paged out and back*. "Quantum swap space" would require quantum memory hardware (a QRAM or long-lived storage register), i.e., it is migration between physical qubits, not serialization.
- **Page cache / buffer cache:** caching is copying plus reuse. Both halves fail: no copy, and any "read" for reuse is a destructive measurement.

**Invariant 2: memory can be read without modification.** Measurement collapses the state **[Proven]**. There is no `PROT_READ` for a qubit; the closest analogue is `PROT_NONE` with a single, destructive, irreversible `read()` of one classical bit per qubit. Debuggers, `ptrace`, `/proc/<pid>/mem`, kernel oops dumps, and memory scrubbing all assume non-destructive reads and are all physically excluded for quantum state.

**Invariant 3: address translation is stateless indirection.** Virtual memory *naming* — a per-process table mapping virtual qubit IDs to physical qubits — is actually fine, and real systems do it: QOS performs spatio-temporal multiplexing of logical circuits onto physical QPU regions **[Demonstrated]** (Giortamis et al., OSDI '25). What breaks is everything *behind* the page table: demand paging (needs copy), overcommit (needs swap), dirty tracking (needs non-destructive read), and NUMA migration (possible only as teleportation, consuming entanglement as fuel).

**Invariant 4: memory persists across context switches.** Idle quantum state decoheres. T1/T2 times on 2026 superconducting hardware are O(100 µs)–O(1 ms) **[Demonstrated]**; a descheduled "quantum process" loses its working set not by eviction policy but by physics, with fidelity decaying exponentially in wall-clock time, F(t) ≈ e^(−t/T2). Error-corrected logical qubits change the constant, not the conclusion: a logical qubit is kept alive by *active* syndrome-measurement cycles (Google's Willow sustains a distance-7 surface-code logical qubit at 0.143% error per cycle, below threshold, Nature 2024 **[Demonstrated]**), so an idle-but-alive quantum page consumes QPU duty cycle continuously. Idle quantum memory is not free; it is a running process.

**Summary: kernel memory invariants vs. quantum mechanics**

| Kernel invariant | Physical law that breaks it | Status | Kernel features lost |
|---|---|---|---|
| State can be copied | No-cloning theorem (linearity of QM) | **[Proven]** | `fork()`, CoW, KSM, snapshots, page cache, backup |
| State can be read non-destructively | Measurement postulate (projective collapse) | **[Proven]** | `ptrace`, core dumps, `/proc/<pid>/mem`, dirty/accessed bits, scrubbing |
| State can be serialized | Tomography cost Θ(4^n/ε²) over copies that cannot exist | **[Proven]** | swap, demand paging, hibernate, checkpoint/restore (CRIU) |
| State persists while descheduled | Decoherence, F(t) ≈ e^(−t/T2); QEC requires active cycles | **[Demonstrated]** | indefinite suspension, idle pages being free |
| Memory is fungible and homogeneous | Per-qubit calibration drift, lattice topology constraints | **[Demonstrated]** | uniform-cost allocation; placement becomes fidelity-critical |

Design consequence for QISA-K: quantum registers must be exposed to the kernel as **linear (affine) resources** — usable at most once along any data path, never duplicated, explicitly consumed by `MEASURE`/`RESET` — closer to Rust move semantics or file descriptors with `O_CLOEXEC` than to pages. This is precisely why Q# restricts qubit access through `use` blocks with scoped lifetimes (Svore et al., arXiv:1803.00652) and why QIR models qubits as opaque pointers that cannot be dereferenced.

What *survives* of virtual memory is exactly its naming layer: indirection, isolation of namespaces, and revocation. A per-process table mapping virtual qubit handles to physical qubits gives the kernel relocation (remap a lease to better-calibrated qubits between jobs), isolation (a process cannot name another's qubits), and revocation (kernel resets and reclaims on `exit()`), without ever copying state. Virtual memory minus paging is a capability system — which is why the proposed syscall interface below is capability-shaped.

---

## Kernel Subsystem Analysis

### Scheduler

What changes: scheduling becomes *circuit batching under coherence deadlines*, not time-slicing. A quantum job is admitted, runs to completion (one shot or a shot batch), and exits; EDF-style admission control replaces CFS-style fair sharing. Preemption of a running circuit is impossible without losing the state — a context switch would require saving quantum state, which is **[Proven]** forbidden (no-cloning) and **[Proven]** lossy (measurement). What is possible, and **[Demonstrated]** by QOS: spatial multiplexing (placing multiple small circuits on disjoint qubit regions of one QPU, with crosstalk-aware placement) and temporal multiplexing (batching jobs into the QPU's classical control pipeline), yielding up to 9.6× utilization gains at 1–3% average fidelity cost. Linux's existing primitives map surprisingly well at the *job* level: a quantum job is closer to a GPU kernel launch than to a thread, and the right scheduling layer is a workqueue + deadline class in a device driver, not a new CFS entity. QNodeOS additionally **[Demonstrated]** that network-node scheduling must interleave application logic with entanglement-generation attempts under hard latency budgets — a real-time co-scheduling problem Linux's `SCHED_DEADLINE` could express, but only on the classical side.

What is impossible: preemptive multitasking *of quantum state*; priority inheritance across a measurement (outcomes are irreversible); migration of a running circuit between QPUs (would require teleporting the full register mid-circuit — **[Theoretical]** possible, **[Speculative]** practical).

What needs emulation: "suspend/resume" becomes checkpoint-by-reexecution — store the classical circuit and inputs, kill the state, re-run later. Valid only for circuits whose preparation is deterministic from classical data.

### Memory manager

Covered in depth above. Summary: the buddy allocator concept survives as a *qubit allocator* (physical qubits are a fixed, small, heterogeneous pool with per-qubit calibration quality — allocation is closer to CPU-affinity-aware hugepage reservation than to page allocation). Per-process virtual-to-physical qubit maps are viable and **[Demonstrated]** (QOS's compiler/placement layer). Demand paging, CoW, swap, KSM (same-page merging — explicitly a cloning operation), and memory compaction via copy are all **[Proven]** incompatible. Compaction survives only as SWAP-gate or teleportation-based *migration*, costing circuit depth: routing on a 2D lattice costs O(√N) SWAP depth per logical move on an N-qubit grid **[Proven]** (graph-distance lower bound). `madvise()`, dirty bits, and reference bits have no quantum analogue because they require observation.

### Filesystem (VFS)

What changes: nothing can store quantum state at rest — there is no quantum disk. Quantum long-term storage would itself be a quantum memory (a register of error-corrected qubits burning syndrome cycles), so a "quantum file" is a *live process*, not data at rest. The honest VFS story: files hold (a) circuit descriptions (OpenQASM 3 / QIR text — ordinary files), (b) classical results (shot histograms — ordinary files), and (c) *handles* to live quantum resources. Option (c) fits Linux's "everything is a file descriptor" model well: a qubit lease can be an anonymous fd (like `memfd`/`dmabuf`), with `read()` = MEASURE (destructive, one-shot), `write()` = gate application via `ioctl`/`io_uring`, `dup()` = must fail with `-EPERM` (duplication is **[Proven]** physically undefined), and `close()` = RESET + free. `sendfile()`, `mmap()` of quantum fds, and `splice()` must be rejected. What needs emulation: persistence = storing the generating circuit plus a re-execution contract. What is impossible: `fsync()` of quantum state; backup; deduplication (cloning); snapshots (cloning).

### Network stack

What changes: quantum networking is not packet forwarding of qubits over sockets. Real quantum network nodes — **[Demonstrated]** by QNodeOS (Delle Donne et al., Nature, 2025) — generate *entanglement* between nodes as the primitive, then consume it for teleportation or QKD. Key inversions of TCP/IP assumptions: (1) no store-and-forward — a quantum repeater cannot buffer-and-retransmit a qubit copy (no-cloning **[Proven]**); repeaters work by entanglement swapping instead **[Demonstrated]** at lab scale. (2) No retransmission: loss of a qubit in flight is unrecoverable; reliability must come from entanglement distillation (many noisy pairs → fewer better pairs, sacrificial, **[Demonstrated]**). (3) Every quantum channel needs a paired classical channel (teleportation requires 2 classical bits per qubit **[Proven]**), so the classical Linux network stack remains load-bearing. A "quantum socket" (`AF_QIPC`) would expose: `connect()` = request entanglement generation, `send()` = teleport (destroys local state), `recv()` = receive corrections and apply them — with hard latency deadlines because the entangled pair decoheres while classical bits are in flight. QuNetSim (DiAdamo et al., arXiv:2003.06397) **[Demonstrated]** (in simulation) that such a layered protocol stack is programmable. What is impossible: multicast (cloning), passive monitoring/tcpdump of qubits (measurement), NAT-style middlebox rewriting, and deep packet inspection — quantum links are end-to-end private by physics, the basis of QKD security **[Proven]** information-theoretically, **[Demonstrated]** commercially.

What needs emulation: congestion control becomes entanglement-rate scheduling; QoS becomes fidelity budgeting.

### Device drivers

This is the one subsystem that ports almost unchanged, because on every real 2026 system the QPU *is already a device*. IBM, Google, and IonQ machines are controlled by racks of classical electronics (AWGs, FPGAs, IonQ's EQC chip-level controllers) driven by classical hosts — Linux hosts, in practice **[Demonstrated]**. A QPU driver looks like a GPU driver with three twists: (1) **hard real-time control path** — feed-forward (measure, decide, apply gate within the coherence window) demands sub-microsecond classical latency, so the inner control loop must live in FPGA firmware below the kernel, with Linux handling only job-level orchestration (the QNodeOS split between a CNPU and a real-time QNPU **[Demonstrated]** exactly this layering); (2) **calibration as first-class state** — gate fidelities drift hour-to-hour; the driver must expose calibration data (a `sysfs` tree of per-qubit T1/T2/error rates) and support recalibration cycles, as QOS's hardware-aware compilation assumes **[Demonstrated]**; (3) **destructive reads** — the completion path returns classical shot data via ordinary DMA, so `io_uring`-style async completion fits naturally. Interrupts, DMA, PCIe enumeration, power management: all classical, all portable.

What is impossible: nothing fundamental — this layer is classical by construction. The risk is latency, not physics.

---

## Survey of Existing Quantum OS Research

All entries below were verified to exist as described (June 2026).

| System | Venue / artifact | What it actually is | OS concepts covered |
|---|---|---|---|
| **QOS** (Giortamis, Romão, Tornow, Bhatotia) | arXiv:2406.19120; USENIX OSDI '25 | Cloud-level quantum OS: hardware-agnostic job API, error mitigation, multiprogramming, spatio-temporal scheduling. Evaluated on IBM hardware with 7,000 real runs; 2.6–456.5× fidelity improvement, up to 9.6× utilization, up to 5× lower wait times **[Demonstrated]** | Scheduler, allocator (qubit placement), job multiplexing |
| **QNodeOS** (Delle Donne, Iuliano, van der Vecht, …, Wehner; Quantum Internet Alliance) | Nature (2025), DOI 10.1038/s41586-025-08704-w; arXiv:2407.18306 | First OS for quantum *network* nodes: ran the same application code on trapped-ion and NV-center hardware; splits a classical network processing unit from a real-time quantum-control unit **[Demonstrated]** | Process model, real-time scheduling, hardware abstraction layer, networking |
| **Quingo** (The Quingo Development Team) | arXiv:2009.01686; ACM TQC (2021) | Programming framework for heterogeneous quantum-classical computing with NISQ timing control; six-phase program lifecycle managed by a runtime **[Demonstrated]** (compiler + runtime artifact) | Runtime/lifecycle model, timing control — the "exec format" layer |
| **QuNetSim** (DiAdamo et al.) | arXiv:2003.06397 | Python simulation framework for quantum networks up to the network layer; real-time simulation suitable for driving lab hardware **[Demonstrated]** (as simulator) | Network stack layering for qubits |
| **Q# / QIR runtime** (Svore et al.; QIR Alliance) | arXiv:1803.00652; QIR spec (Linux Foundation QIR Alliance) | High-level language with scoped qubit lifetimes; LLVM-based IR treating qubits as opaque, non-dereferenceable handles; runtime profiles for restricted hardware classes | ABI/IR — the "ELF format" of the quantum stack |
| **eQASM** (Fu et al.) | HPCA 2019; arXiv:1808.02449 | First executable QISA, instantiated as a 32-bit ISA on superconducting hardware, with VLIW timing and SOMQ execution **[Demonstrated]** | The ISA layer itself |
| **OpenQASM 3** (Cross et al.) | ACM TQC 3(3), 2022; arXiv:2104.14722 | Circuit description language formalizing real-time vs. near-time classical computation; the de facto interchange format on IBM hardware **[Demonstrated]** | Instruction stream format; timing semantics |

The pattern across every verified system: nobody runs OS logic on qubits. Every project — including the two flagship 2025 results (QOS at OSDI, QNodeOS in Nature) — is a classical OS/runtime *managing* quantum resources, differing only in where they draw the real-time boundary. This is strong empirical convergence on the hybrid architecture proposed below.

---

## Feasibility Classification

Classes: **(A)** directly portable · **(B)** quantum-aware rewrite · **(C)** classical emulation layer · **(D)** fundamentally incompatible.

| Kernel component | Class | Rationale (one line) |
|---|---|---|
| Boot / init (start_kernel) | A | Pure classical control flow; QPU is enumerated later like any device **[Demonstrated]** on all real systems |
| Interrupt handling / IRQ core | A | Readout-complete events are ordinary device interrupts; sub-µs feed-forward lives in firmware, not the kernel |
| Device driver core (PCIe, DMA, sysfs) | A | QPU control electronics are classical peripherals **[Demonstrated]** |
| Syscall machinery / VFS plumbing | A | Classical; quantum resources ride on fd semantics (with `dup`/`mmap` blocked) |
| Scheduler (CFS time-slicing) | B | Job-level batch/EDF admission replaces preemption; circuits run-to-completion under coherence deadlines **[Demonstrated]** (QOS) |
| Qubit allocator ("buddy" for qubits) | B | Fixed heterogeneous pool, calibration-aware placement, linear-resource accounting; no overcommit |
| Virtual memory: translation/naming | B | Virtual→physical qubit maps are viable and demonstrated; everything behind the table changes |
| `fork()` for quantum state | D | No-cloning **[Proven]**; only move (teleport) or re-execute semantics exist |
| Copy-on-write | D | "Copy" branch is physically undefined **[Proven]** |
| Swap / demand paging of qubits | D | Serialization = tomography = Θ(4^n/ε²) destructive measurements over copies that cannot exist **[Proven]** |
| Page cache / KSM dedup / snapshots | D | All are copying or non-destructive reading **[Proven]** |
| `ptrace` / core dumps / debuggers on quantum state | D | Non-destructive inspection forbidden by measurement postulate **[Proven]** |
| Filesystems (data at rest) | C | Store circuits (QASM/QIR) + classical results; "quantum persistence" emulated as re-execution contracts |
| Quantum resource handles in VFS | B | One-shot destructive `read`, no `dup`/`mmap`; capability-style fds |
| Network stack (classical TCP/IP) | A | Required as the classical channel of every quantum protocol **[Proven]** (teleportation needs 2 classical bits/qubit) |
| Quantum networking (`AF_QIPC`) | B | Entanglement generation/consumption with deadlines; QNodeOS shows the shape **[Demonstrated]** |
| Packet buffering / retransmit / multicast for qubits | D | Store-and-forward and multicast are cloning **[Proven]** |
| Security: memory isolation between quantum jobs | B | Physical isolation + crosstalk budgeting replace page-table protection; observation-based auditing impossible |
| Timekeeping (clocksource, hrtimers) | A | Becomes *more* critical: gate scheduling is deterministic-time; ns-precision timers are load-bearing |
| Power management | B | Logical qubits consume active error-correction duty cycle even when "idle" **[Demonstrated]** (Willow-class QEC cycles) |
| Console / tty / userspace ABI | A | Untouched; users see job APIs, not qubits |

Tally: the majority of kernel *code* is class A/B — because the majority of a quantum computer is classical. The class-D list is short but absolute: it is exactly the set of features whose semantics are copying or non-destructive observation.

---

## Proposed Architecture: Hybrid Kernel with QPU Dispatch

The only design consistent with the analysis above — and with every verified real system — is: **Linux runs unmodified on a classical co-processor (the host), and quantum work is dispatched to the QPU through a narrow driver boundary**, exactly as GPUs are managed today, plus hard-real-time firmware below the driver for feed-forward.

### Syscall additions

Four syscalls (realistically: one `ioctl`/`io_uring` family on a `/dev/qpu0` character device — shown as syscalls for clarity):

| Syscall | Signature (sketch) | Semantics |
|---|---|---|
| `qalloc` | `int qalloc(int qpu_fd, unsigned n_qubits, struct qalloc_hints *h)` | Lease `n` physical (or logical) qubits; hints carry topology/fidelity needs; returns a *qubit-set fd* (capability). Fails with `-EBUSY` under pool exhaustion — no overcommit, ever |
| `qexec` | `int qexec(int qset_fd, const void *qir_blob, size_t len, struct qexec_params *p)` | Submit a verified QIR/OpenQASM circuit for run-to-completion execution (`p` = shots, deadline, feed-forward table). Async; completion via `io_uring` CQE |
| `qmeasure` | `ssize_t qmeasure(int qset_fd, void *out, size_t out_len)` | Destructive readout of designated qubits into classical shadow buffer; consumes the lease's live state; explicitly *not* `read(2)`-idempotent |
| `qfree` | `int qfree(int qset_fd)` | RESET all leased qubits, return them to the pool, close capability |

Enforced invariants at the syscall boundary: qubit-set fds return `-EPERM` on `dup()`, `fork()` marks them close-on-fork (move semantics: at most one owner — the linear-type discipline from the QISA section, kernel-enforced), `mmap()` is rejected, and `qexec` blobs are statically checked (no gate on an unleased qubit, no use-after-measure without `RESET`).

**Error semantics** (the cases that have no classical precedent):

| Errno | Returned by | Meaning |
|---|---|---|
| `-EBUSY` | `qalloc` | Qubit pool exhausted; no overcommit exists because no swap exists |
| `-ETIME` | `qexec` | Circuit depth exceeds the coherence/QEC budget declared by the device |
| `-ENOEXEC` | `qexec` | Verifier rejection: unleased qubit, use-after-measure, or malformed QIR |
| `-EIO` | `qmeasure` | Readout completed below the fidelity floor in `qexec_params` (calibration drift) |
| `-ESTALE` | `qexec` | Lease's placement invalidated by a recalibration cycle; caller must re-`qalloc` |
| `-EPERM` | `dup`/`mmap`/`sendfile` on qset fd | Operation is copying or non-destructive observation; physically undefined |

**Userspace flow** (sketch, error handling elided):

```c
int qpu = open("/dev/qpu0", O_RDWR | O_CLOEXEC);

struct qalloc_hints h = { .min_t2_us = 200, .topology = QTOPO_ANY };
int qset = qalloc(qpu, 2, &h);                  /* lease 2 qubits        */

struct qexec_params p = {
    .shots    = 4096,                            /* near-time repetition  */
    .deadline = QDEADLINE_RELAXED,               /* EDF admission hint    */
    .fidelity_floor = 95,                        /* percent, else -EIO    */
};
qexec(qset, bell_qir, bell_qir_len, &p);         /* async submit          */
/* ... completion via io_uring CQE ... */

uint8_t out[2 * 4096 / 8];
ssize_t n = qmeasure(qset, out, sizeof out);     /* destructive, one-shot */

qfree(qset);                                     /* RESET + return pool   */
```

Everything the application keeps — `out`, histograms, derived estimates — is classical and flows through the unmodified VFS, network stack, and memory manager. The quantum state never crosses the syscall boundary; only its classical shadow does. This is the precise sense in which Linux "supports quantum hardware" without any quantum semantics leaking into core kernel code.

### Kernel driver boundary

Three layers, mirroring the QNodeOS CNPU/QNPU split and the QOS scheduler stack:

1. **`qpu_core` (kernel, soft real-time):** lease accounting, job queue with EDF admission by coherence deadline, calibration `sysfs` tree, multiplexing policy (spatial placement of concurrent leases with crosstalk budgets).
2. **`qpu_hw` (kernel, per-vendor):** translates QIR to the vendor QISA (eQASM-class), DMAs pulse schedules to the control stack, fields completion IRQs.
3. **Control firmware (FPGA/ASIC, hard real-time, below Linux):** µs-scale pulse playback, readout discrimination, feed-forward branching. The kernel never sits in this loop — Linux interrupt latency is µs-scale with unbounded tails and cannot meet coherence-window deadlines reliably.

### Architecture diagram

```
 ┌────────────────────────────────────────────────────────────────────┐
 │                       USERSPACE (unmodified ABI)                   │
 │   app ──> libqpu (Qiskit / Q# / Quingo-style runtime)              │
 │              │  QIR / OpenQASM 3 blobs + classical params          │
 ├──────────────┼─────────────────────────────────────────────────────┤
 │              ▼            LINUX KERNEL (classical host CPU)        │
 │   syscall/io_uring:  QALLOC ─ QEXEC ─ QMEASURE ─ QFREE             │
 │              │                                                     │
 │   ┌──────────▼───────────┐      ┌───────────────────────────┐      │
 │   │ qpu_core             │      │ classical kernel, intact: │      │
 │   │  lease/capability mgr│      │ sched, mm, VFS, net, drv  │      │
 │   │  EDF job queue       │◄────►│ (results stored as plain  │      │
 │   │  placement/multiplex │      │  files; circuits as data) │      │
 │   └──────────┬───────────┘      └───────────────────────────┘      │
 │   ┌──────────▼───────────┐                                         │
 │   │ qpu_hw (vendor)      │   QIR → QISA compile, DMA, IRQ          │
 │   └──────────┬───────────┘                                         │
 ├──────────────┼── PCIe / Ethernet ── (kernel never below this line) ┤
 │              ▼     REAL-TIME CONTROL STACK (FPGA/ASIC firmware)    │
 │     pulse playback · readout discrimination · feed-forward (<1 µs) │
 ├────────────────────────────────────────────────────────────────────┤
 │              ▼                 QPU (cryostat / trap)               │
 │     q0 … qN-1  — linear resources: no copy, no peek, no swap       │
 └────────────────────────────────────────────────────────────────────┘
```

Hardware context for sizing (verified June 2026): IBM's Nighthawk (120 qubits/module, 5,000 two-qubit gates at launch **[Demonstrated]**; ~7,500 by end of 2026, scaling toward three linked modules, and the Loon/Kookaburra qLDPC line targeting the 2029 Starling system at 200 logical qubits and 10^8 gates — all roadmap **[Speculative]**); Google's Willow (105 qubits, below-threshold distance-7 surface code, Λ ≈ 2.14 per distance step) **[Demonstrated]**; IonQ Forte Enterprise (36 qubits, 99.6% 2Q fidelity, all-to-all) shipping **[Demonstrated]**, with Tempo-class ~100-qubit systems and 256-qubit EQC-based systems slated for 2026 — roadmap **[Speculative]** until shipped. At these scales the QPU pool an OS must manage is 10²–10³ physical qubits — a *small-device* allocation problem, far below where sophisticated mm machinery would even pay for itself.

---

## Conclusion and Feasibility Verdict

**Can the Linux kernel be ported to run *on* quantum hardware?** No — and this is not an engineering gap but a theorem-level incompatibility. The kernel's deepest invariants (state can be copied, read without disturbance, and suspended indefinitely) are each individually refuted by quantum mechanics: copying by no-cloning **[Proven]**, inspection by the measurement postulate **[Proven]**, and suspension by decoherence **[Demonstrated]** across all hardware platforms. `fork()`, CoW, swap, page cache, core dumps, and packet retransmission are not "hard to port"; they are undefined operations on quantum state. Moreover, running *classical* kernel logic on qubits would be strictly worse than pointless: reversible unitary execution of deterministic branching code gains nothing (quantum speedups are algorithm-specific — O(√N) Grover oracle queries **[Proven]**, super-polynomial factoring speedup over the best known classical algorithm via Shor **[Proven]** relative to known classical methods, O(poly(log N, κ, 1/ε)) HHL linear-system solves **[Proven]** *only* under the fine print: efficient |b⟩ state preparation, sparse well-conditioned A, and an output you can use without full state readout — caveats Aaronson's analysis makes essential **[Theoretical]** for end-to-end advantage) while paying ~10³–10⁴× physical-per-logical qubit overhead for fault tolerance under current surface-code parameters **[Demonstrated]** trendlines.

**Can Linux be the operating system *of* a quantum computer?** Yes — it already is, on effectively every deployed system **[Demonstrated]**. The defensible project named "QuantumLinux" is precisely the hybrid architecture above: an upstreamable `qpu` driver subsystem with capability-style leases, EDF circuit scheduling, calibration-aware placement, and a four-call dispatch interface — a kernel-resident sibling of what QOS implements in the cloud layer and QNodeOS implements for network nodes. The research frontier is real but narrow and classical: multiplexing policy, real-time boundaries, linear-typed resource enforcement at the syscall layer, and (as fault tolerance matures toward IBM's 2029 Starling-class targets) kernel-managed logical-qubit pools whose "idle" cost is a continuous error-correction duty cycle.

**Verdict: literal port — infeasible in principle, as a corollary of the [Proven] no-cloning theorem and measurement postulate. Hybrid control-plane Linux — feasible, demonstrated in adjacent systems, and the only architecture worth building [Demonstrated].**

### Open problems worth pursuing

Concrete, tractable research directions that fall out of this analysis, ordered by nearness:

1. **Mainline `qpu` subsystem.** No upstream Linux subsystem exists for QPUs; every vendor ships an out-of-tree userspace stack. A vendor-neutral char-device + QIR-verifier + lease-manager core (the `qpu_core`/`qpu_hw` split above) is implementable today against cloud APIs and would standardize the boundary the way DRM did for GPUs **[Speculative]** as to adoption, not feasibility.
2. **Kernel-enforced linear types for resources.** The use-at-most-once discipline qubits demand is useful beyond quantum (DMA buffers, enclave memory). A general `O_LINEAR` fd semantic — no `dup`, ownership transfer on `SCM_RIGHTS`, kernel-verified single consumer — is a self-contained VFS research project **[Speculative]**.
3. **EDF scheduling under calibration drift.** Coherence deadlines are not constants; they drift with recalibration cycles. Scheduling theory for deadlines that are themselves stochastic processes, with QOS-style multiplexing as the workload model, is open **[Theoretical]**.
4. **Logical-qubit pool accounting.** Once Starling-class machines (200 logical qubits, 2029 target) exist, "idle" logical qubits consume continuous QEC duty cycle — a resource model with no analogue in cgroup accounting. Designing the controller (per-cgroup syndrome-cycle budgets?) can start now against simulators **[Speculative]**.
5. **`AF_QIPC` socket semantics.** QNodeOS demonstrates the node OS; the Linux-side socket family for entanglement leases — deadline-bound `connect()`, fidelity-annotated `recv()` — has no reference design **[Speculative]**.

---

## References

1. W. K. Wootters and W. H. Zurek, "A single quantum cannot be cloned," *Nature* 299, 802–803 (1982). https://www.nature.com/articles/299802a0
2. C. H. Bennett, G. Brassard, C. Crépeau, R. Jozsa, A. Peres, W. K. Wootters, "Teleporting an unknown quantum state via dual classical and Einstein–Podolsky–Rosen channels," *Physical Review Letters* 70, 1895–1899 (1993). https://link.aps.org/doi/10.1103/PhysRevLett.70.1895
3. P. W. Shor, "Polynomial-Time Algorithms for Prime Factorization and Discrete Logarithms on a Quantum Computer," *SIAM Journal on Computing* 26(5), 1484–1509 (1997). arXiv:quant-ph/9508027. https://arxiv.org/abs/quant-ph/9508027
4. L. K. Grover, "A fast quantum mechanical algorithm for database search," *Proc. 28th ACM STOC*, 212–219 (1996). arXiv:quant-ph/9605043. https://arxiv.org/abs/quant-ph/9605043
5. R. Raussendorf and H. J. Briegel, "A One-Way Quantum Computer," *Physical Review Letters* 86, 5188–5191 (2001). https://link.aps.org/doi/10.1103/PhysRevLett.86.5188
6. E. Farhi, J. Goldstone, S. Gutmann, M. Sipser, "Quantum Computation by Adiabatic Evolution," arXiv:quant-ph/0001106 (2000). https://arxiv.org/abs/quant-ph/0001106
7. D. Aharonov, W. van Dam, J. Kempe, Z. Landau, S. Lloyd, O. Regev, "Adiabatic Quantum Computation is Equivalent to Standard Quantum Computation," *SIAM Journal on Computing* 37(1), 166–194 (2007). arXiv:quant-ph/0405098. https://epubs.siam.org/doi/10.1137/S0097539705447323
8. D. Aharonov and M. Ben-Or, "Fault-Tolerant Quantum Computation With Constant Error Rate," *SIAM Journal on Computing* (2008). arXiv:quant-ph/9906129. https://arxiv.org/abs/quant-ph/9906129
9. A. W. Harrow, A. Hassidim, S. Lloyd, "Quantum algorithm for solving linear systems of equations," *Physical Review Letters* 103, 150502 (2009). arXiv:0811.3171. https://arxiv.org/abs/0811.3171
10. S. Aaronson, "Read the fine print," *Nature Physics* 11, 291–293 (2015). https://www.nature.com/articles/nphys3272
11. J. Preskill, "Quantum Computing in the NISQ era and beyond," *Quantum* 2, 79 (2018). arXiv:1801.00862. https://arxiv.org/abs/1801.00862
12. X. Fu, L. Riesebos, et al., "eQASM: An Executable Quantum Instruction Set Architecture," *Proc. 25th IEEE International Symposium on High Performance Computer Architecture (HPCA)* (2019). arXiv:1808.02449. https://arxiv.org/abs/1808.02449
13. A. W. Cross, A. Javadi-Abhari, T. Alexander, N. de Beaudrap, L. S. Bishop, S. Heidel, C. A. Ryan, P. Sivarajah, J. Smolin, J. M. Gambetta, B. R. Johnson, "OpenQASM 3: A Broader and Deeper Quantum Assembly Language," *ACM Transactions on Quantum Computing* 3(3), 1–50 (2022). arXiv:2104.14722. https://arxiv.org/abs/2104.14722
14. K. M. Svore, A. Geller, M. Troyer, et al., "Q#: Enabling scalable quantum computing and development with a high-level DSL," *Proc. Real World Domain Specific Languages Workshop (RWDSL)* (2018). arXiv:1803.00652. https://arxiv.org/abs/1803.00652
15. QIR Alliance (Linux Foundation), "Quantum Intermediate Representation" specification. https://github.com/qir-alliance ; Microsoft Learn overview: https://learn.microsoft.com/en-us/azure/quantum/concepts-qir
16. E. Giortamis, F. Romão, N. Tornow, P. Bhatotia, "QOS: A Quantum Operating System," *Proc. 19th USENIX Symposium on Operating Systems Design and Implementation (OSDI '25)* (2025). arXiv:2406.19120. https://arxiv.org/abs/2406.19120 ; https://www.usenix.org/conference/osdi25/presentation/giortamis
17. The Quingo Development Team, "Quingo: A Programming Framework for Heterogeneous Quantum-Classical Computing with NISQ Features," *ACM Transactions on Quantum Computing* (2021). arXiv:2009.01686. https://arxiv.org/abs/2009.01686
18. S. DiAdamo, J. Nötzel, B. Zanger, M. M. Beşe, "QuNetSim: A Software Framework for Quantum Networks," arXiv:2003.06397 (2020). https://arxiv.org/abs/2003.06397
19. C. Delle Donne, M. Iuliano, B. van der Vecht, …, S. Wehner (Quantum Internet Alliance), "An operating system for executing applications on quantum network nodes," *Nature* (2025). DOI 10.1038/s41586-025-08704-w. arXiv:2407.18306. https://www.nature.com/articles/s41586-025-08704-w
20. Google Quantum AI and Collaborators, "Quantum error correction below the surface code threshold," *Nature* (published online December 2024). DOI 10.1038/s41586-024-08449-y. https://www.nature.com/articles/s41586-024-08449-y
21. IBM Quantum, "IBM lays out clear path to fault-tolerant quantum computing" (Starling/Loon/Kookaburra roadmap, 2025) and IBM Newsroom, "IBM Delivers New Quantum Processors…" (Nighthawk, November 12, 2025). https://www.ibm.com/quantum/blog/large-scale-ftqc ; https://newsroom.ibm.com/2025-11-12-ibm-delivers-new-quantum-processors,-software,-and-algorithm-breakthroughs-on-path-to-advantage-and-fault-tolerance ; roadmap: https://www.ibm.com/roadmaps/quantum/
22. IonQ, "Compare Quantum Systems" (Forte Enterprise: 36 qubits; Tempo: ~100 qubits, specifications) and "IonQ Achieves Landmark Result…" (256-qubit EQC-based systems, 2026). https://www.ionq.com/quantum-systems/compare ; https://www.ionq.com/news/ionq-achieves-landmark-result-setting-new-world-record-in-quantum-computing
23. C. H. Bennett, E. Bernstein, G. Brassard, U. Vazirani, "Strengths and Weaknesses of Quantum Computing," *SIAM Journal on Computing* 26(5), 1510–1523 (1997). arXiv:quant-ph/9701001. https://arxiv.org/abs/quant-ph/9701001
24. C. H. Bennett, "Time/Space Trade-Offs for Reversible Computation," *SIAM Journal on Computing* 18(4), 766–776 (1989). DOI 10.1137/0218053. https://epubs.siam.org/doi/10.1137/0218053
