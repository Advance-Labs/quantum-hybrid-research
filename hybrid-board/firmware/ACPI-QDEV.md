# ACPI-QDEV — Quantum Device (QDEV) ACPI Object Specification

**Document:** `hybrid-board/firmware/ACPI-QDEV.md`
**Series:** Advance Labs Quantum/Classical Hybrid Research — HybridBoard, Stage 3 (Firmware / UEFI Extension)
**Version:** v0.1
**Status:** design concept — not a product specification
**TRL:** 2 — paper design only. No shipping platform exposes a QPU through UEFI/ACPI today.

> **Blanket tag (per research doc §8):** every design element in this document is
> **[Theoretical]**. Precedents cited are real and individually tagged. Sources of
> truth: [docs/research/03-hybrid-board.md](../../docs/research/03-hybrid-board.md)
> (§5.2 memory regions, §8.2 QDEV concept, §8.3 Linux platform driver model) and
> [docs/workflows/03-hybridboard-workflow.md](../../docs/workflows/03-hybridboard-workflow.md)
> (Stage 3 steps 5–7, Stage 4 step 1). Flit and channel semantics are defined in
> [QCX-PROTOCOL-v0.1.md](../architecture/QCX-PROTOCOL-v0.1.md); boot-time population
> of these objects is specified in [QPUINIT.md](QPUINIT.md). Design precedent:
> ACPI specification §6 (Device Configuration).

---

## 1. Scope and Naming

`QDEV` is the proposed ACPI device object for a QCX-attached QPU (research doc §8.2),
identified in the vendor namespace by `_HID` = `QCX0001`.

**Naming rule:** the ACPI specification reserves leading-underscore names (`_XXX`) for
spec-defined objects. QDEV-specific objects therefore use **non-underscore vendor
names** — `QTOP`, `QCAL`, `QTHM` — exactly as named in research doc §8.2. The only
underscore names QDEV uses are the spec-defined ones it implements or analogizes
(`_HID`, `_CID`, `_UID`, `_STA`, `_CRS`, `_PSx`).

## 2. QDEV Field Set (canonical, research doc §8.2)

| QDEV field | Content |
|---|---|
| `_HID` / `_CID` | QCX endpoint identity (`_HID` = `QCX0001`; `_CID` = `QCX0000`, generic QCX-endpoint class) |
| `QTOP` | qubit count, coupling-map blob (analog of NUMA SLIT/SRAT for qubit topology) |
| `QCAL` | handle to non-volatile calibration store |
| `QTHM` | cryo-plant state machine (WARM / COOLING / COLD / REGEN) surfaced to OSPM power management |
| `_PSx` analog | QPU "power states" map to *availability* states, since the cryoplant cannot be cycled like a PCIe function |

This v0.1 additionally defines `QAVL` (§5.2), a read-only availability object that
carries the POST availability state from [QPUINIT.md](QPUINIT.md) §2.2 into the
namespace; it is supporting machinery for the `_PSx` analog row, not a sixth
canonical field.

---

## 3. Object Semantics

### 3.1 `_HID` / `_CID`

7-character PNP-style IDs (3-letter vendor prefix `QCX` + 4 hex digits). `_HID`
`QCX0001` identifies this QDEV revision; `_CID` `QCX0000` lets a generic class driver
bind when no revision-specific driver exists. The Linux `platform_driver` binds on the
`QCX0001` `_HID` (see "Linux Driver Model").

### 3.2 `QTOP` — qubit topology/count

Returns the binary blob laid out in §4. It is the qubit-topology analog of NUMA
SLIT/SRAT (research doc §8.2): the OS scheduler-facing description of how many
physical qubits exist and which pairs are coupled. Contents are populated at boot
from the Quantum Capability Structure ([QPUINIT.md](QPUINIT.md) §2.3) and are static
for the OS session; qubits that fail the POST functional census are reported via
availability/sysfs, not by mutating `QTOP`.

### 3.3 `QCAL` — calibration store handle

Returns a handle (package: base address, length, format version — §4.3) to the
**non-volatile calibration store**: per-qubit frequencies, pulse amplitudes, crosstalk
matrices, O(n²) worst case for n qubits (research doc §5.2). The store is read over
the QCX BULK channel; `QCAL` conveys *where and how big*, never the contents, which
can reach MB-class for large n.

### 3.4 `QTHM` — cryoplant state machine

Returns the current plant state, surfaced read-only to OSPM:

| Value | State | Meaning |
|---|---|---|
| 0 | `WARM` | plant at ambient; QPU unavailable |
| 1 | `COOLING` | cooldown in progress — **hours–days** for dilution systems **[Demonstrated]** (research doc §8.1, [41]) |
| 2 | `COLD` | base temperature; QPU may be available |
| 3 | `REGEN` | regeneration/maintenance cycle; QPU unavailable |

State changes raise `Notify(QPU0, 0x80)` so the OS can late-attach without polling
(§6). Whether four states suffice for multi-cryostat SC plants is an open question
deferred to v0.2 (workflow Risks table, #10).

### 3.5 `_PSx` analog — availability, not power

`_PS0`/`_PS3` are implemented but deliberately weak: they gate **only** the QCX
endpoint and sequencer power, because **the cryoplant cannot be cycled like a PCIe
function** (research doc §8.2) — "powering off" a dilution refrigerator is a
days-long thermodynamic event, not a D-state transition. QPU "power states"
therefore map to *availability* states (`QAVL`, §5.2):
`Offline / NotCold / Calibrating / Degraded / Online`, mirroring
`QPU_AVAILABILITY` in [QPUINIT.md](QPUINIT.md) §2.2.

---

## 4. Binary Layouts (field-level offsets/sizes)

### 4.1 `QTOP` blob layout

Widths match the QCX flit header: virtual qubit IDs are 16-bit (`vqid[16]`,
[QCX-PROTOCOL-v0.1.md](../architecture/QCX-PROTOCOL-v0.1.md)).

| Offset | Size | Field | Description |
|---|---|---|---|
| 0x00 | 4 B | `Signature` | ASCII `QTOP` |
| 0x04 | 2 B | `Version` | 0x0001 |
| 0x06 | 2 B | `HeaderLength` | 16 (0x10) |
| 0x08 | 2 B | `QubitCount` | physical qubit count *n* (u16) |
| 0x0A | 1 B | `Modality` | same code table as QCAP ([QPUINIT.md](QPUINIT.md) §2.3): 0 SC transmon, 1 trapped ion, 2 photonic, 3 neutral atom, 4 silicon spin |
| 0x0B | 1 B | `TopologyClass` | 0 = heavy-hex, 1 = square lattice, 2 = all-to-all, 3 = arbitrary edge list |
| 0x0C | 2 B | `EdgeCount` | coupler edge count *m* (u16) |
| 0x0E | 2 B | `Reserved` | 0 |
| 0x10 | 4·*m* B | `EdgeList` | *m* records of (`u16` src vqid, `u16` dst vqid), little-endian |

Total size: 16 + 4·*m* bytes.

### 4.2 Worked example: Heron-class 133-qubit heavy-hex map

IBM Heron is a 133-qubit heavy-hex device **[Demonstrated]** (research doc §3.1,
[2][3]); its heavy-hex lattice has 150 coupler edges. The corresponding blob:

| Field | Value |
|---|---|
| `QubitCount` | 133 (0x0085) |
| `Modality` | 0 (SC transmon) |
| `TopologyClass` | 0 (heavy-hex) |
| `EdgeCount` | 150 (0x0096) |
| Blob size | 16 + 4 × 150 = **616 B (0x268)** |

First header bytes, little-endian:
`51 54 4F 50  01 00  10 00  85 00  00  00  96 00  00 00` followed by 150 edge
records (`00 00 01 00` for the 0–1 coupler, etc.).

### 4.3 `QCAL` handle package

`QCAL` returns an ACPI `Package` rather than a raw blob:

| Element | Type | Description |
|---|---|---|
| 0 | Integer (u64) | calibration-store base address (BULK-channel address space; mirrors QCAP `CalStorePointer`) |
| 1 | Integer (u64) | store length in bytes |
| 2 | Integer (u16) | calibration format version |
| 3 | Integer (u64) | last-update timestamp (ns since epoch; 0 = never calibrated) |

---

## 5. ASL Example Block

Syntactically plausible v0.1 fragment for a single QPU device node. Addresses and
interrupt numbers are illustrative.

```asl
DefinitionBlock ("qdev.aml", "SSDT", 2, "ADVLAB", "QDEVTBL", 0x00000001)
{
    Scope (\_SB)
    {
        Device (QPU0)
        {
            Name (_HID, "QCX0001")     // QCX endpoint identity (research doc §8.2)
            Name (_CID, "QCX0000")     // generic QCX-endpoint class
            Name (_UID, Zero)

            Method (_STA, 0, NotSerialized)
            {
                // Device is present and enumerable even when QPU_NOT_COLD:
                // availability is a QAVL/QTHM concern, not presence.
                Return (0x0F)
            }

            Name (_CRS, ResourceTemplate ()
            {
                // QCX MMIO window: sequencer config, timing epoch, error
                // counters (research doc §5.2, region 1)
                QWordMemory (ResourceConsumer, PosDecode, MinFixed, MaxFixed,
                    NonCacheable, ReadWrite,
                    0x0000000000000000,         // Granularity
                    0x0000004000000000,         // Min
                    0x000000400FFFFFFF,         // Max
                    0x0000000000000000,         // Translation
                    0x0000000010000000)         // Length: 256 MiB
                // Syndrome/result ring-buffer window: host DRAM, DMA-written
                // by the QCX endpoint (research doc §5.2, region 2)
                QWordMemory (ResourceConsumer, PosDecode, MinFixed, MaxFixed,
                    Cacheable, ReadWrite,
                    0x0000000000000000,
                    0x0000004010000000,
                    0x000000401FFFFFFF,
                    0x0000000000000000,
                    0x0000000010000000)
                // Event interrupts: RT-flit drop, epoch resync, QTHM change
                Interrupt (ResourceConsumer, Level, ActiveHigh, Exclusive) { 48, 49, 50 }
            })

            // QTOP — qubit topology/count blob (§4.1). Heron-class 133-qubit
            // heavy-hex example: 616 B total; header shown, edge list
            // populated by firmware from the Quantum Capability Structure.
            Method (QTOP, 0, NotSerialized)
            {
                Return (Buffer (0x0268)
                {
                    0x51, 0x54, 0x4F, 0x50,    // 'QTOP'
                    0x01, 0x00,                // Version 1
                    0x10, 0x00,                // HeaderLength 16
                    0x85, 0x00,                // QubitCount 133
                    0x00,                      // Modality: SC transmon
                    0x00,                      // TopologyClass: heavy-hex
                    0x96, 0x00,                // EdgeCount 150
                    0x00, 0x00,                // Reserved
                    0x00, 0x00, 0x01, 0x00     // edge (0,1); 149 more follow
                    // ... firmware fills the remaining edge records
                })
            }

            // QCAL — handle to the non-volatile calibration store (§4.3)
            Method (QCAL, 0, NotSerialized)
            {
                Return (Package (0x04)
                {
                    0x0000004100000000,        // store base (BULK address space)
                    0x0000000000200000,        // length: 2 MiB
                    0x0001,                    // format version
                    0x0000000000000000         // last-update timestamp
                })
            }

            // Cryoplant controller mailbox (read-only to OSPM)
            OperationRegion (PLNT, SystemMemory, 0x000000400FFF0000, 0x10)
            Field (PLNT, DWordAcc, NoLock, Preserve)
            {
                THMS, 32,                      // 0 WARM / 1 COOLING / 2 COLD / 3 REGEN
                AVLS, 32                       // 0 Offline / 1 NotCold / 2 Calibrating
                                               // / 3 Degraded / 4 Online
            }

            // QTHM — cryoplant state machine surfaced to OSPM (§3.4)
            Method (QTHM, 0, NotSerialized)
            {
                Return (THMS)
            }

            // QAVL — availability state backing the _PSx analog (§3.5)
            Method (QAVL, 0, NotSerialized)
            {
                Return (AVLS)
            }

            // _PSx analog: availability, not power (§3.5). These methods gate
            // only the QCX endpoint/sequencer; the cryoplant cannot be cycled
            // like a PCIe function (research doc §8.2).
            Method (_PS0, 0, NotSerialized) { /* enable sequencer rails  */ }
            Method (_PS3, 0, NotSerialized) { /* quiesce sequencer only  */ }
        }
    }
}
```

---

## 6. Enumeration Flow: Firmware → OSPM

1. **DXE:** `QpuDxe` trains the QCX link (BULK channel) and reads the Quantum
   Capability Structure — POST phases P1–P2 ([QPUINIT.md](QPUINIT.md) §3).
2. **SSDT synthesis:** firmware populates the `QDEV` node — `QTOP` from the
   capability structure's coupling-map blob, `QCAL` from `CalStorePointer`, `QTHM`
   bound to the plant-controller mailbox — and publishes the table.
3. **POST completes** in bounded time; on most SC-variant boots the recorded status
   is `QPU_NOT_COLD` ([QPUINIT.md](QPUINIT.md) §4) and `EFI_QPU_PROTOCOL` is not
   installed, but the `QDEV` node is *always* present so the OS can observe `QTHM`.
4. **ExitBootServices → OSPM:** the OS parses the namespace, finds `\_SB.QPU0` with
   `_HID` `QCX0001`, and hands it to the matching driver.
5. **Driver bind:** the Linux `platform_driver` probes (see "Linux Driver Model"),
   reads `QTOP`/`QCAL`/
   `QTHM`/`QAVL`, creates `/dev/qpu0` and the sysfs tree.
6. **Late attach:** when the cryoplant reaches `COLD` (hours–days after power-on for
   dilution systems **[Demonstrated]** [41]), the platform raises
   `Notify(QPU0, 0x80)`; the driver re-evaluates availability and transitions the
   device toward `online` without a reboot.

```mermaid
sequenceDiagram
    participant FW as UEFI QpuDxe (DXE)
    participant TBL as ACPI tables (SSDT: QDEV)
    participant OS as OSPM / Linux ACPI core
    participant DRV as qcx bus + platform_driver
    participant USR as Userspace runtime (Qiskit/CUDA-Q-class)
    FW->>FW: POST P1–P2: QCX link train (BULK), QCAP read
    FW->>TBL: synthesize QDEV (QTOP, QCAL, QTHM, _CRS)
    FW->>OS: ExitBootServices (QPU never boot-critical)
    OS->>TBL: enumerate \_SB.QPU0, match _HID QCX0001
    OS->>DRV: platform_driver probe
    DRV->>DRV: read QTOP/QCAL/QTHM/QAVL; create /dev/qpu0 + sysfs
    TBL-->>DRV: Notify(QPU0, 0x80) on QTHM change (late attach)
    USR->>DRV: io_uring-style circuit submission via /dev/qpu0
```

---

## Linux Driver Model

All of this section is **[Theoretical]** design per research doc §8.3; the cited
patterns (PCIe/CXL core, io_uring, DPDK core isolation, CUDA-Q runtime coupling) are
real. The compilable reference scheduler that sits above this model is
`hybrid-board/scheduler/quantum_scheduler.c` (workflow Stage 4). (This section is
deliberately unnumbered: the workflow Stage 4 acceptance criteria key on the exact
heading `## Linux Driver Model`.)

### `qcx` bus driver

- A `qcx` bus driver modeled on the existing **PCIe/CXL core** (research doc §8.3):
  `bus_type qcx_bus` registers at init, enumerates QPU *functions* behind each QCX
  host endpoint, and owns the RT/BULK channel state (epoch, drop counters).
- A Linux **`platform_driver` binds on the ACPI `QCX0001` `_HID`** (workflow Stage 4
  step 1); probe reads `QTOP`/`QCAL`/`QTHM`/`QAVL`, registers one `qcx` device per
  QPU function, and installs the ACPI notify handler for late attach (§6).
- Until `QTHM` = `COLD` and POST-equivalent runtime checks pass, the device exists
  but reports `availability = not_cold` — mirroring the firmware's "late-attach
  device whose `QPU_NOT_COLD` status may persist across many OS boots"
  (research doc §8.1).

### Character device: `/dev/qpu0`

One character device per QPU function. It exposes exactly the three surfaces of
research doc §8.3:

1. **Circuit submission queue** — io_uring-style submission/completion ring pair
   (see "Submission-queue model" below), mapping onto the research doc §5.2 memory
   regions.
2. **mmap'd result rings** — the syndrome/result ring buffers of research doc §5.2:
   host DRAM, DMA-written by the QCX endpoint, carrying measurement bitstreams and
   timestamps. Read-only to userspace; the kernel never copies the hot path.
3. **Calibration sysfs tree** — see "sysfs tree layout" below.

Illustrative mmap window layout:

| mmap offset | Region | Backing (research doc §5.2) |
|---|---|---|
| 0x0000 | submission ring (SQ) | host DRAM |
| 0x1000 | completion ring (CQ) | host DRAM |
| 0x2000+ | syndrome/result rings | host DRAM, DMA-written by QCX endpoint |

### Submission-queue model

- **Unit of submission:** a re-executable circuit object — OpenQASM/QIR description
  or transpiled binary from the circuit object store (research doc §5.2) — plus shot
  count, parameter bindings, and an optional seed. Re-execution from circuit + seed
  is the **only** restore semantics: quantum state cannot be checkpointed, paged,
  migrated, or suspend-to-disked **[Proven]** (no-cloning, Wootters & Zurek [40];
  measurement collapse — research doc §5.2). The ABI therefore has *no*
  save/restore/migrate operations by construction; cancel means "abandon remaining
  shots", never "resume later from saved state".
- **Two submission classes:**
  - `QPU_SUBMIT_BULK` — ordinary circuit jobs; queued, reordered, throttled freely
    (BULK channel semantics).
  - `QPU_SUBMIT_RT` — real-time class for QEC decode-feedback and
    variational/calibration inner loops, the only demonstrated µs-class need
    **[Demonstrated]** (research doc §9.2, [32]). RT submitters are expected to pin
    to isolated cores — the same isolation pattern used for DPDK/real-time
    networking today (research doc §8.3) — because a decoder slower than the ~1 µs
    syndrome cycle accrues Θ(t) backlog **[Proven]** (queueing argument,
    research doc §4.1).
- **No preemption:** shots are non-preemptible at microsecond granularity
  (research doc §8.3); the scheduler may interleave *between* shots/segments only.
- **Completion:** CQ entries carry discriminated results (O(1) byte per qubit per
  measurement) or pointers into the result rings for raw-IQ calibration reads
  (research doc §4.2).

### sysfs tree layout

```text
/sys/bus/qcx/
├── drivers/
│   └── qcx_qpu/                      # platform_driver bound on _HID QCX0001
└── devices/
    └── qpu0/
        ├── modality                  # sc-transmon | trapped-ion | photonic
        │                             #   | neutral-atom | si-spin (QTOP codes, §4.1)
        ├── qubit_count               # decimal n, from QTOP
        ├── topology                  # binary attribute: raw QTOP blob (§4.1)
        ├── qthm                      # WARM | COOLING | COLD | REGEN (§3.4)
        ├── availability              # offline | not_cold | calibrating
        │                             #   | degraded | online (§3.5)
        ├── functional_mask           # POST qubit-census bitmap (QPUINIT.md §3, P6)
        ├── calibration/              # the calibration sysfs tree (research doc §8.3)
        │   ├── format_version        # from QCAL (§4.3)
        │   ├── last_update_ns        # from QCAL (§4.3)
        │   └── q0000/ … qNNNN/       # one directory per physical qubit:
        │       ├── freq_hz           #   frequency
        │       ├── t1_us             #   relaxation time
        │       ├── t2_us             #   dephasing time
        │       └── readout_fidelity
        └── stats/
            ├── qcx_rt_drop_count     # late/dropped RT flits — the QCX no-retry
            │                         #   rule: a late flit is discarded and
            │                         #   counted, never re-delivered
            │                         #   (QCX-PROTOCOL-v0.1.md, Stage 2)
            ├── qcx_epoch_resync_count
            ├── shots_completed
            └── shots_aborted
```

### Userspace

Qiskit/CUDA-Q-class runtimes sit atop the device node; CUDA-Q's tight GPU coupling
on DGX Quantum — <4 µs GPU↔QPU round trip, 3.3 µs measured — is the demonstrated
precedent for the runtime layer **[Demonstrated]** (research doc §8.3, [32][33]).
The QCX target the runtime sees is the ≤2 µs loop / ~10 GB/s sustained envelope of
[QCX-PROTOCOL-v0.1.md](../architecture/QCX-PROTOCOL-v0.1.md) **[Theoretical]**.

---

## 7. Open Questions (carried from the workflow Risks table)

| # | Question | Disposition |
|---|---|---|
| 1 | Does `QTHM`'s four-state model (WARM/COOLING/COLD/REGEN) suffice for multi-cryostat SC plants, or does QDEV need per-zone thermal objects? | Deferred to v0.2 of this document (workflow risk #10) **[Theoretical]** |
| 2 | Should the RT channel's per-flit FEC strength be a negotiable link parameter surfaced through QDEV/sysfs? | Stage 2 (QCX protocol) question; QDEV reserves no fields for it in v0.1 (workflow risk #9) **[Theoretical]** |

## 8. Cross-References

- POST sequence, `EFI_QPU_PROTOCOL`, QCAP layout, POST codes, variant differences:
  [QPUINIT.md](QPUINIT.md).
- Flit format (256 B, 16 B header / 224 B payload / 16 B CRC-FEC), RT/BULK channels,
  no-retry rule, ≤2 µs latency SLA, ~10 GB/s bandwidth:
  [QCX-PROTOCOL-v0.1.md](../architecture/QCX-PROTOCOL-v0.1.md).
- Research grounding: [docs/research/03-hybrid-board.md](../../docs/research/03-hybrid-board.md)
  §5.2 (mappable regions; no quantum registers in the address space **[Proven]**),
  §8.2 (QDEV field set), §8.3 (Linux platform driver model). Bracketed reference
  numbers ([32], [40], [41], etc.) are the research doc's reference list.
