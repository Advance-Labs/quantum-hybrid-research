# QLOS v0.1 — The QuantumLinux OS Runtime (Design Document)

**Document:** quantum-linux/qos/QLOS-DESIGN-v0.1.md
**Status:** BINDING interface contract for the v0.1 builders (toolchain, qsyscalls, scheduler)
**Sources of truth:** docs/research/02-quantum-linux.md · docs/workflows/02-linux-workflow.md (Stages 4–5) · quantum-linux/isa-spec/QISA-v0.1.yaml · quantum-linux/emulator/qcpu.py · quantum-linux/kernel-patches/qsyscall.h

## 1. Abstract

QLOS (QuantumLinux OS runtime) v0.1 is a **user-space realization** of the research doc's
control-plane architecture: a classical runtime that leases qubits, verifies and schedules
circuits, and returns only classical measurement shadows — the four-call
`QALLOC`/`QEXEC`/`QMEASURE`/`QFREE` discipline of `qsyscall.h`, implemented in Python today
against the `qcpu.py` statevector emulator, designed so the *same ABI* later fronts real
hardware over a QCX-attached QPU (docs/research/03-hybrid-board.md). Nothing in QLOS runs *on*
qubits — incoherent under the **[Proven]** no-cloning theorem and measurement postulate — and
it gives quantum hardware a normalized, classical-style development process mirroring
edit/cc/exec/gdb. **Naming:** this runtime is called **QLOS**, never "QOS", to avoid collision
with the QOS quantum operating system the research doc cites (Giortamis et al., OSDI '25);
here "QOS" always means that paper.

## 2. Position in the stack

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │ DEVELOPER TOOLING  editor ──> bell.qs ──> qas.py ──> bell.qobj.json │
 │                        ▲────── qdis.py (disassembler) ◄────┘        │
 ├─────────────────────────────────────────────────────────────────────┤
 │ QLOS RUNTIME (user-space control plane; all state here is CLASSICAL)│
 │   qos/qsyscalls.py   QLOSRuntime: qalloc · qexec · qmeasure · qfree │
 │        │             (errno contract mirrors qsyscall.h exactly)    │
 │   qos/scheduler.py   QProcess ─ LeaseManager ─ QPUScheduler         │
 │        │             linear-capability leases · deadline-aware FIFO │
 │        │             with coherence-budget admission control        │
 ├────────┼────────────────────────────────────────────────────────────┤
 │ DEVICE LAYER  today:    emulator/qcpu.py (dense statevector, ≤24 q) │
 │               tomorrow: /dev/qpu0 over QCX (Quantum Compute Express)│
 │               per hybrid-board docs — same 4-call ABI [Theoretical] │
 │   q0 … qN-1 — linear resources: no copy, no peek, no swap [Proven]  │
 └─────────────────────────────────────────────────────────────────────┘
```

Only the classical shadow (measurement bits, histograms, lease metadata) crosses a boundary
upward; only verified programs cross downward (research doc, userspace-flow section).

## 3. The quantum process model

A **QProcess** = classical execution context (ordinary, copyable Python state: pid, name,
stats) + **qubit leases** (linear capabilities / qset fds; one owner, never duplicated) +
**submitted circuits** (queued/completed jobs; run-to-completion, never preempted) + a per-
lease **measurement ring buffer** (bounded buffer of shot snapshots — the only
quantum→classical channel; mirrors the hybrid-board doc's DMA result ring buffers).

### Lifecycle states

- `NEW` — created; no leases held (spawn; a `fork()` child starts here).
- `READY` — holds ≥1 lease, no jobs in flight (via `qalloc`, or jobs drained by `qmeasure`).
- `RUNNING` — classical side executing (transient; inside any QLOS call).
- `BLOCKED_ON_QPU` — submitted jobs not yet complete; `qmeasure` would block (via `qexec`).
- `ZOMBIE` — exited; leases revoked (RESET + returned to pool); stats retained for reaping.

### fork / exec semantics (no-cloning corollary)

**`fork()`:** the classical context forks (child gets a copy, state `NEW`). Leases are
**NEVER duplicated** — qset capabilities are close-on-fork (`QSET_F_CLOFORK`): parent keeps
them, child gets none; a duplicated lease would copy live quantum state, **[Proven]**
physically undefined (no-cloning, Wootters & Zurek 1982; research doc, Invariant 1).
**`exec()`:** the classical image is replaced and all leases revoked (`qfree`: RESET + return
to pool) — revocation destroys state, never copies, always physically allowed (research doc:
qubit handles behave like `O_CLOEXEC` fds).

### Lease exclusivity rules

1. One owner per lease; ownership moves, never copies (linear/affine discipline).
2. A physical qubit belongs to at most one live lease; no overcommit, ever — no swap exists
   for quantum state **[Proven]** (serialization = tomography over impossible copies).
3. `dup()` of a qset fd → `-EPERM`. Extracting additional use from a *consumed* lease (second
   `qmeasure`, or `qexec` after `qmeasure`) → `-EPERM` — same violation class: reuse of a
   use-at-most-once capability. (`qsyscall.h` assigns `-EPERM` to `dup`/`mmap` but names no
   errno for consumed-lease reuse; mapping it to `-EPERM` is a v0.1 ABI completion made here.)
4. Lifecycle (mirrors `qlease_desc.state`): `QLEASE_STATE_LIVE` → (`qmeasure`) →
   `QLEASE_STATE_CONSUMED` → (`qfree`); recalibration moves LIVE → `QLEASE_STATE_STALE`
   (`qexec` then fails `-ESTALE`; only `qfree` remains valid).

## 4. Syscall semantics

Python calls mirror `qsyscall.h` **semantically**: same names, same struct fields as keyword
arguments / result fields, same errnos — always sourced from Python's `errno` module (values
differ across platforms; never hard-code integers). `__NR_*` and `QPU_IOC_*` are the header's
provisional design-artifact numbers. Errno → exception mapping: §8.3.

| Call | Python signature (`QLOSRuntime`) | Mirrors (qsyscall.h) | Errno failures (exact header set) | Blocking behavior |
|---|---|---|---|---|
| QALLOC | `qalloc(n_qubits, *, min_t2_us=0, topology=QTOPO_ANY) -> int` (qset fd) | `__NR_qalloc` 463 / `QPU_IOC_QALLOC`; `struct qalloc_hints {min_t2_us, topology}` | `-EBUSY` pool exhausted (no overcommit, ever) | **Never blocks** — fails fast; there is no swap to wait on |
| QEXEC | `qexec(qset_fd, qobj, *, shots=1, deadline_us=QDEADLINE_RELAXED, fidelity_floor=0) -> int` (job id) | `__NR_qexec` 464 / `QPU_IOC_QEXEC`; `struct qexec_submit {qir_blob, len, params}`; `struct qexec_params {shots, deadline, fidelity_floor, ff_table…}` | `-ENOEXEC` verifier rejection (unleased qubit, use-after-measure, malformed program); `-ETIME` estimated duration exceeds remaining lease coherence budget (or its own deadline); `-ESTALE` lease staled by recalibration | **Never blocks** — verify + admit synchronously, then enqueue; execution deferred (runtime analogue of the header's async submit / io_uring CQE) |
| QMEASURE | `qmeasure(qset_fd) -> MeasureResult` | `__NR_qmeasure` 465 / `QPU_IOC_QMEASURE`; fills `struct qmeasure_result {shots, n_qubits, fidelity_est, flags, payload_len, shadow[]}` | `-EIO` readout below the max `fidelity_floor` of drained jobs (call fails *instead of* returning data; the lease is still consumed — the destructive readout happened, it was just bad) | **Blocks** until all queued jobs on the lease complete (v0.1: synchronously drives `QPUScheduler.run_pending()`), then destructively drains the ring buffer. NOT `read(2)`-idempotent |
| QFREE | `qfree(qset_fd) -> int` (0) | `__NR_qfree` 466 / `QPU_IOC_QFREE` | none of the quantum table (always succeeds for a known fd — revocation/RESET is always physically allowed, even on STALE/CONSUMED leases) | **Never blocks**; cancels the lease's still-queued jobs, RESETs, returns qubits to the pool, closes the capability |

Cross-cutting (header's enforced-invariants block): `QLOSRuntime.dup(qset_fd)` always raises
`-EPERM` (`QERR_PHYS_UNDEFINED`: duplication is copying — **[Proven]** undefined). Unknown fd
on any call → `-EBADF` — ordinary POSIX, deliberately *not* in the header's quantum errno
table. `lease_info(qset_fd)` mirrors `QPU_IOC_LEASE_INFO` / `struct qlease_desc`.
`recalibrate()` bumps the calibration epoch and stales all LIVE leases — the `-ESTALE` test
seam (workflow Risk 6: drift deferred; this stubs the recalibration event).

## 5. Scheduling

**Model: deadline-aware FIFO with admission control; run-to-completion; one circuit at a time.**

- **No preemption, ever.** Preempting a running circuit requires saving quantum state —
  **[Proven]** forbidden (no-cloning) and **[Proven]** lossy (measurement); jobs run to
  completion (research doc, Scheduler subsystem: EDF-style admission replaces CFS).
- **QPU multiplexing:** exactly one circuit executes at a time — today *statevector
  exclusivity* (one dense statevector per executing job), on hardware the single-QPU pipeline.
  Leases **time-share** the QPU: `LeaseManager` partitions the qubit *pool* (spatial
  accounting, `-EBUSY` on exhaustion); `QPUScheduler` serializes circuit *execution*.
  QOS-style spatial multiplexing of concurrent circuits is **not** modeled.
- **Dispatch order:** finite-deadline jobs (`deadline_us > 0`) first, by ascending absolute
  deadline (ties: submission order); `QDEADLINE_RELAXED` (0) jobs follow FIFO. Absolute
  deadline = scheduler virtual clock (`virtual_now_cycles`, advanced by each executed job's
  estimated cost) + `deadline_us * CYCLES_PER_US` at submit. Deadlines are soft in v0.1: a
  miss increments `stats()["deadline_misses"]`; the job still runs.
- **Admission control (the real-time constraint):** every lease carries a coherence budget in
  emulated cycles — `min_t2_us * CYCLES_PER_US` when the `qalloc` hint is given, else the
  runtime default. At submit, `estimate_cycles(qobj)` (static per-shot estimate) is checked
  against the lease's **remaining** budget; exceeding it — or the job's own `deadline_us`
  budget — rejects the job at submit with **`-ETIME`** (`QERR_COHERENCE_BUDGET`: "circuit
  depth exceeds the coherence/QEC budget declared by the device"). Admitted jobs *reserve*
  their estimate, deducted at submit (conservative EDF-admission).
- **Cost table** (module constants in `qos/scheduler.py`): `COST_1Q = 1`, `COST_2Q = 3`,
  `COST_MEASURE = 10`, `COST_RESET = 12`, `FMR`/`BRN` = 0 (classical feed-forward — lives in
  control firmware on real hardware **[Demonstrated]**, eQASM/QNodeOS), `QWAIT` = its
  immediate; `CYCLES_PER_US = 10`. Ratios loosely follow superconducting gate-vs-readout
  durations but are **[Theoretical]** policy parameters, not hardware claims (the `QWAIT`
  counter is not a timing model — workflow Risk 3). Real coherence windows are per-shot and
  firmware-enforced **[Demonstrated]**; QLOS's cumulative per-lease budget is a deliberately
  conservative *classical-side admission policy*, not a decoherence model **[Theoretical]**.

## 6. Toolchain and the QOBJ v0.1 object format

### 6.1 The `.qs` assembly text format

**Exactly** the format `qcpu.assemble()` already parses — the toolchain adds no syntax and
must delegate parsing to it. UTF-8, line-oriented; one instruction per line; blank lines
ignored; `;` starts a comment.
- A leading token ending in `:` defines a label at the next instruction index (e.g. `.skip:`);
  a label may be followed by an instruction on the same line; duplicates rejected.
- Opcodes case-insensitive (canonicalized upper); must be QISA-K mnemonics. `->` and `,` are
  interchangeable operand separators; conventional spellings: `MEASURE q0 -> c0`,
  `FMR c0 -> r1`, `CNOT q0, q1`, `BRN r1, .skip`, `RX q0, 1.5707963`.
- Registers: `q<int>` qubit, `c<int>` shadow, `r<int>` GPR. Angles: float literals;
  immediates: non-negative decimal ints; `BRN` targets must be defined (decode-time check).

### 6.2 QOBJ v0.1 — the assembled object format (a JSON envelope; the "ELF" of this stack)

```json
{
  "format": "QOBJ", "format_version": "0.1",
  "isa": {"name": "QISA-K", "version": "0.1"},
  "requirements": {"n_qubits": 2, "n_shadow": 2, "n_gpr": 0},
  "entry": 0,
  "instructions": [{"opcode": "RESET", "operands": [0], "line_no": 2, "source": "RESET   q0"}],
  "labels": {},
  "stats": {"gate_counts": {"RESET": 2, "H": 1, "CNOT": 1, "MEASURE": 2},
            "two_qubit_gate_count": 1, "measure_count": 2, "qwait_cycles": 0, "instruction_count": 6},
  "source_sha256": "<hex sha256 of the .qs source text>"
}
```

`requirements` are *minimums* (highest register index used + 1); `stats` are **static**
assembled counts (distinct from `QCPU`'s runtime counters); `entry` is always 0 in v0.1;
`instructions[*].operands` follow ISA operand order, with `line_no`/`source` carried so `qdis`
emits listing-grade output and diagnostics survive the round trip.

### 6.3 Assembler / disassembler responsibilities

- **`toolchain/qas.py`** — `.qs` → `QObj`. Validation **at assemble time** against
  `QISA-v0.1.yaml` is the load-time protection layer (the MMU analogue: reject before any
  state exists): parse via `qcpu.assemble(text, isa)` (opcode/operand-kind checks against the
  YAML-loaded `ISA`), then run the static verifier via a throwaway
  `qcpu.QCPU(n_qubits=max(requirements.n_qubits, 1))` `.verify(program)` — a lease exactly
  the program's own size. Violations raise `qcpu.QISAVerifierError` (errno `-ENOEXEC`); the
  lease-relative `no-gate-on-unleased-qubit` rule is re-checked at `qexec` vs the real lease.
- **`toolchain/qdis.py`** — `QObj` → canonical `.qs` text. **Round-trip law (binding):**
  `assemble(disassemble(q))` yields identical `instructions`, `labels`, `requirements`, and
  `stats` (only `source_sha256` may differ).
- `qexec` re-verifies every submitted program with the emulator's own verifier before
  execution (defense in depth: an object file is untrusted input, exactly as ELF is).

## 7. The normalized developer workflow

| Step | Quantum (QLOS) | Classical analogue |
|---|---|---|
| edit | write `bell.qs` | edit `hello.c` |
| assemble | `qas.py bell.qs -o bell.qobj.json` (verify vs QISA-v0.1.yaml) | `cc hello.c` |
| submit | `qexec` via `QLOSRuntime` (lease, verify, admit, run); a `qrun` convenience CLI is deferred to v0.2 | `exec` |
| measure | `qmeasure` → counts histogram | read stdout |
| debug | statevector inspection via `QCPU._debug_statevector()` | `gdb` |

**Debugging honesty:** amplitude inspection is **only possible in simulation** — no physical
machine offers it: non-destructive reads are excluded by the measurement postulate
**[Proven]**, copies by no-cloning **[Proven]**; on hardware "inspecting the state" becomes
state tomography at Θ(4ⁿ/ε²) destructive shots over re-preparations **[Proven]** (research
doc, Invariants 1–2). The underscore name marks it off-limits to anything kernel-visible.

### Worked end-to-end example: `bell.qs` → counts

```asm
; bell.qs — uncorrected Bell pair (qcpu.BELL_UNCORRECTED_ASM)
        RESET   q0
        RESET   q1
        H       q0
        CNOT    q0, q1
        MEASURE q0 -> c0
        MEASURE q1 -> c1
```

```python
from qas import assemble_file        # CLI: python toolchain/qas.py bell.qs -o bell.qobj.json
from qsyscalls import QLOSRuntime
rt = QLOSRuntime(n_pool_qubits=8, seed=42)
qobj = assemble_file("bell.qs")
fd  = rt.qalloc(qobj.n_qubits, min_t2_us=200)        # lease 2 qubits (research-doc flow)
job = rt.qexec(fd, qobj, shots=4096, fidelity_floor=95)
res = rt.qmeasure(fd)                                # blocks; destructive, one-shot
print(res.counts())                                  # {'00': ~2048, '11': ~2048}; never '01'/'10'
rt.qfree(fd)                                         # RESET + return to pool
```

## 8. Public API contract (BINDING for builders)

Module layout — `qcpu.py` must not be modified, its public API must not change, and the
existing 72-test suite `emulator/test_hello_quantum.py` must keep passing:

```
quantum-linux/
├── toolchain/   qas.py · qdis.py · test_toolchain.py    (builder A)
└── qos/         qsyscalls.py (builder B) · scheduler.py (builder C) · test_qos.py (combined suite)
```

Ground rules (binding): Python ≥3.11, full type annotations, module/function docstrings
stating emulated-vs-real with research-doc citations, `__main__` guards, numpy/pyyaml-only
runtime; **no** torch/pennylane/qiskit anywhere under quantum-linux/. Import seam: modules do
`sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emulator"))`, `import qcpu`;
`qos/` imports the toolchain likewise (`parents[1] / "toolchain"`). Test basenames are
distinct so pytest collects cleanly. Run: `/tmp/qhr-venv/bin/python -m pytest quantum-linux/`.

### 8.1 `toolchain/qas.py`

```python
QOBJ_FORMAT: str = "QOBJ"; QOBJ_VERSION: str = "0.1"
@dataclass(frozen=True)
class QObj:
    isa_name: str; isa_version: str                # "QISA-K", "0.1"
    n_qubits: int; n_shadow: int; n_gpr: int       # requirements (max index + 1)
    entry: int                                     # 0 in v0.1
    instructions: tuple[qcpu.Instruction, ...]
    labels: dict[str, int]
    stats: dict[str, Any]                          # static counts (schema §6.2)
    source_sha256: str
    def to_json(self, *, indent: int | None = 2) -> str: ...
    @classmethod
    def from_json(cls, text: str) -> "QObj": ...   # raises QISAVerifierError on bad envelope
    def to_program(self) -> qcpu.Program: ...      # for QCPU.run / .verify
def assemble(source: str, *, isa: qcpu.ISA | None = None) -> QObj: ...
def assemble_file(path: str | Path, *, isa: qcpu.ISA | None = None) -> QObj: ...
def main(argv: list[str] | None = None) -> int: ...   # CLI: qas.py SRC.qs [-o OUT.qobj.json]
```

Errors: `assemble`/`assemble_file`/`from_json` raise `qcpu.QISAVerifierError` (carries
`.errno == -ENOEXEC`); no new exception types in the toolchain.

### 8.2 `toolchain/qdis.py`

```python
def disassemble(qobj: QObj) -> str: ...                # canonical .qs text (round-trip law §6.3)
def disassemble_file(path: str | Path) -> str: ...
def main(argv: list[str] | None = None) -> int: ...    # CLI: qdis.py IN.qobj.json [-o OUT.qs]
```

### 8.3 `qos/qsyscalls.py`

```python
# Constants mirrored from qsyscall.h (names identical):
QTOPO_ANY: int; QTOPO_LINE: int; QTOPO_GRID: int; QTOPO_ALL2ALL: int
QDEADLINE_RELAXED: int          # 0
QMR_F_PARTIAL: int              # ring overflow / fewer shots than requested
QLEASE_STATE_LIVE: int; QLEASE_STATE_CONSUMED: int; QLEASE_STATE_STALE: int
QLEASE_MAX_QUBITS: int          # 128 (header); emulated pool further capped by qcpu.MAX_QUBITS
class QLOSError(OSError): ...                  # .qlos_errno: int (negative, from errno module)
class PoolExhaustedError(QLOSError): ...       # -EBUSY   (QERR_POOL_EXHAUSTED)
class CoherenceBudgetError(QLOSError): ...     # -ETIME   (QERR_COHERENCE_BUDGET)
class VerifierRejectError(QLOSError): ...      # -ENOEXEC (QERR_VERIFIER_REJECT)
class FidelityFloorError(QLOSError): ...       # -EIO     (QERR_FIDELITY_FLOOR)
class LeaseStaleError(QLOSError): ...          # -ESTALE  (QERR_LEASE_STALE)
class PhysUndefinedError(QLOSError): ...       # -EPERM   (QERR_PHYS_UNDEFINED)
class BadDescriptorError(QLOSError): ...       # -EBADF   (classical; not in the quantum table)
@dataclass(frozen=True)
class LeaseInfo:                               # mirror of struct qlease_desc
    lease_id: int; n_qubits: int; cal_epoch: int; state: int; flags: int
    vq_to_pq: tuple[int, ...]
@dataclass(frozen=True)
class MeasureResult:                           # mirror of struct qmeasure_result
    shots: int; n_qubits: int
    fidelity_est: int                          # percent; emulated constant (§9)
    flags: int                                 # QMR_F_PARTIAL bit
    snapshots: tuple[dict[str, int], ...]      # per-shot shadow files, e.g. {"c0": 1, "c1": 1}
    def counts(self) -> dict[str, int]: ...    # bitstring histogram, key "c{n-1}…c1c0"
    def packed_shadow(self) -> bytes: ...      # shot-major: bit k = shot*n_qubits + qubit,
                                               # LSB-first per byte; len = (n*shots + 7) // 8
class QLOSRuntime:
    def __init__(self, n_pool_qubits: int = 8, *, seed: int | None = None,
                 isa: qcpu.ISA | None = None, coherence_budget_cycles: int = 10_000,
                 readout_fidelity: int = 100, ring_capacity_shots: int = 65_536) -> None: ...
    def qalloc(self, n_qubits: int, *, min_t2_us: int = 0,
               topology: int = QTOPO_ANY) -> int: ...
    def qexec(self, qset_fd: int, qobj: QObjLike | str, *, shots: int = 1,
              deadline_us: int = QDEADLINE_RELAXED, fidelity_floor: int = 0) -> int: ...
    def qmeasure(self, qset_fd: int) -> MeasureResult: ...
    def qfree(self, qset_fd: int) -> int: ...
    def dup(self, qset_fd: int) -> NoReturn: ...       # always PhysUndefinedError (-EPERM)
    def lease_info(self, qset_fd: int) -> LeaseInfo: ...
    def recalibrate(self) -> int: ...                  # new cal_epoch; stales LIVE leases
    def stats(self) -> dict[str, Any]: ...             # delegates to QPUScheduler.stats()
```

Notes: `qexec`'s `qobj` parameter is `scheduler.QObjLike | str` — `qas.QObj` satisfies the
`QObjLike` protocol. `qexec` accepting `str` assembles on the fly via `qas.assemble` (parity
with `QCPU.run`). The C ABI's `qexec` returns 0; the Python runtime returns the job id (≥ 0) —
information-compatible. `readout_fidelity` exists because the noiseless emulator would
otherwise make `-EIO` unreachable; tests lower it to exercise that path. `QLOSRuntime`
composes one root `QProcess` (pid 1) + `LeaseManager` + `QPUScheduler`; multi-process
scenarios use §8.4 directly.

### 8.4 `qos/scheduler.py`

```python
CYCLES_PER_US: int = 10
COST_1Q: int = 1; COST_2Q: int = 3; COST_MEASURE: int = 10; COST_RESET: int = 12
class QProcState(enum.Enum):
    NEW = "NEW"; READY = "READY"; RUNNING = "RUNNING"
    BLOCKED_ON_QPU = "BLOCKED_ON_QPU"; ZOMBIE = "ZOMBIE"
def estimate_cycles(qobj: QObj) -> int: ...       # static per-shot cost (table §5)
@dataclass
class Lease:                                       # kernel-side lease record
    lease_id: int; owner_pid: int; n_qubits: int; vq_to_pq: tuple[int, ...]
    cal_epoch: int; state: int                     # QLEASE_STATE_*
    coherence_budget_cycles: int; coherence_remaining_cycles: int
    ring: collections.deque                        # measurement ring buffer (bounded)
class QProcess:
    def __init__(self, pid: int, name: str = "") -> None: ...
    pid: int; name: str; state: QProcState; leases: dict[int, Lease]
    def fork(self, child_pid: int) -> "QProcess": ...   # classical copy; NO leases (§3)
    def exec_image(self, name: str) -> None: ...        # replace image; leases revoked (§3)
    def exit(self) -> None: ...                         # -> ZOMBIE; leases revoked
class LeaseManager:
    def __init__(self, n_pool_qubits: int, *, default_budget_cycles: int = 10_000,
                 ring_capacity_shots: int = 65_536) -> None: ...
    def allocate(self, proc: QProcess, n_qubits: int, *, min_t2_us: int = 0,
                 topology: int = QTOPO_ANY) -> Lease: ...   # raises PoolExhaustedError
    def release(self, lease: Lease) -> None: ...            # RESET + return to pool
    def recalibrate(self) -> int: ...                       # bump epoch; LIVE -> STALE
    def free_qubits(self) -> int: ...
class QPUScheduler:
    def __init__(self, lease_mgr: LeaseManager, *, seed: int | None = None,
                 isa: qcpu.ISA | None = None) -> None: ...
    def submit(self, lease: Lease, qobj: QObj, *, shots: int = 1,
               deadline_us: int = 0, fidelity_floor: int = 0) -> int: ...
        # verify (VerifierRejectError) -> admit (CoherenceBudgetError / LeaseStaleError)
        # -> reserve budget -> enqueue; returns job id
    def run_pending(self, max_jobs: int | None = None) -> int: ...
        # dispatch per §5; one circuit at a time, run-to-completion; each job executes on a
        # FRESH qcpu.QCPU sized to the lease (statevector exclusivity; shots start at |0...0>
        # per QCPU.run_shots); results append to the lease's ring. Returns jobs executed.
    def stats(self) -> dict[str, Any]: ...
        # binding keys: jobs_submitted, jobs_completed, jobs_rejected (dict by errno name),
        # jobs_cancelled, deadline_misses, virtual_now_cycles, gate_counts (aggregated),
        # two_qubit_gate_count, measure_count, shot_count
```

## 9. v0.1 limitations and future work

| # | Limitation | Honest status |
|---|---|---|
| 1 | Noiseless statevector backend; `fidelity_est` is the constant `readout_fidelity`; `-EIO` reachable only via that knob | emulation artifact; real readout fidelity drifts **[Demonstrated]** |
| 2 | Temporal multiplexing only; no QOS-style spatial multiplexing of concurrent circuits | spatial multiplexing **[Demonstrated]** (QOS, OSDI '25), out of scope |
| 3 | Lease state does not persist across `qexec` jobs (each shot starts at \|0…0⟩ per `QCPU.run_shots`); no cross-job entanglement | matches the emulator's shot model |
| 4 | Coherence budget = classical cycle-count admission policy, not a decoherence model; cost constants are policy parameters | **[Theoretical]**; real windows firmware-enforced **[Demonstrated]** |
| 5 | `BRN` feed-forward executes in the emulator instruction loop; on hardware it lives in control firmware inside the coherence window | **[Demonstrated]** boundary (eQASM, QNodeOS); workflow Risk 3 |
| 6 | Linear-capability rules enforced in user space only (no kernel `O_LINEAR` fds) | research-doc open problem #2 **[Speculative]**; workflow Risk 5 |
| 7 | Pool ≤ `qcpu.MAX_QUBITS` = 24 (16·2ⁿ-byte statevector) — an emulator-capacity limit, **not** the **[Proven]** Θ(4ⁿ/ε²) tomography bound | do not conflate (workflow Prerequisites note) |
| 8 | No quantum networking / `AF_QIPC`; single node only | excluded (workflow Risk 8) **[Speculative]** |
| 9 | Cooperative single-threaded scheduler; no classical-side concurrency (circuit preemption is **[Proven]** impossible regardless) | v0.2 candidate |

**Future work — QCX integration:** the device layer behind `QPUScheduler.run_pending()` is the
single seam to replace. Per docs/research/03-hybrid-board.md, a **QCX (Quantum Compute
Express)** endpoint **[Theoretical]** presents exactly the shape QLOS assumes: parameterized
gate opcodes expanded at a QPU-side sequencer (waveform caching), measurement bitstreams
DMA-written into host-DRAM **result ring buffers** (the hardware form of §3's per-lease ring),
and a calibration store backing `cal_epoch`/`recalibrate()`. The 4-call ABI, errno contract,
and QOBJ format survive that swap; only `estimate_cycles()` and the fidelity source change.
