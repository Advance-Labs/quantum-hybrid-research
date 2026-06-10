# QCX (Quantum Compute Express) Bus Protocol Specification — v0.1

**Document:** QCX-PROTOCOL-v0.1.md
**Series:** Advance Labs Quantum/Classical Hybrid Research — `hybrid-board/` tree
**Date:** June 2026
**Status:** TRL 2 — concept formulated, no implementation. Design concept — not a product specification.
**Source of truth:** [docs/research/03-hybrid-board.md](../../docs/research/03-hybrid-board.md) §4 (QCX); process defined in [docs/workflows/03-hybridboard-workflow.md](../../docs/workflows/03-hybridboard-workflow.md) (Stage 2). All figures (≤2 µs loop, ~1–10 GB/s, ~10 B/gate, ≤10 m optical) are imported from the research doc unchanged.

Everything in this specification is **[Theoretical]** design work unless a statement is explicitly tagged otherwise; demonstrated anchors are cited where they constrain the design.

---

## 1. Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are to be interpreted as in RFC 2119. Normative requirements apply to the *design concept*; no conforming implementation exists (TRL 2).

---

## 2. Layering

QCX is a **quantum transaction layer**. It does **not** define a new PHY or link layer; it adopts CXL 3.1's **256 B latency-optimized flit** as its PHY/link layer **[Demonstrated]** (research doc §4.3) and rides the PCIe 6.x PHY at 64 GT/s. CXL 3.1 retimers achieve <12 ns pin-to-pin **[Demonstrated]**, and PCIe-class PHY traversal is ~100 ns-class — both inside the QCX transport budget (§5).

```
+---------------------------------------------------------------+
| QCX transaction layer (this specification)      [Theoretical] |
|   RT channel (time-triggered, no retry)  |  BULK channel      |
|   GATE / PULSE / MEAS / SYNC / RESULT    |  (CXL.io: CAL,     |
|                                          |   waveform tables) |
+---------------------------------------------------------------+
| CXL 3.1 link layer: 256 B latency-optimized flit [Demonstrated]|
+---------------------------------------------------------------+
| PCIe 6.x PHY, 64 GT/s; optical extension ≤10 m (~50 ns fiber  |
| delay) for the HybridBoard-SC shielding boundary [Theoretical] |
+---------------------------------------------------------------+
```

**Physical reach:** for the superconducting variant the QCX link MUST cross the cryostat/classical shielding boundary on **optical fiber, ≤10 m** (~50 ns fiber delay — within budget per research doc §4.1/§7.1) **[Theoretical]**. For HybridBoard-RT/-Spin, intra-chassis electrical reach MAY be used; ≤10 m is an upper bound, not a requirement.

**Key departures from PCIe/CXL semantics** (research doc §4.3) **[Theoretical]**:

1. **Timestamped execution**, not load/store ordering — gates execute at `t_exec`, not on arrival.
2. **No retry on the real-time channel** — a late flit is a discarded flit plus an error counter, because re-delivered pulses are physically meaningless after the coherence window.
3. A separate **bulk channel** (ordinary CXL.io semantics) for calibration data and waveform-table uploads.

---

## 3. Channel Model

| Channel | Semantics | Carries | Retry |
|---|---|---|---|
| **RT** (real-time) | Time-triggered: flits are admitted into pre-reserved slots and execute at `t_exec` | GATE, PULSE, MEAS, SYNC, RESULT | **MUST NOT retransmit** (§8) |
| **BULK** | Ordinary CXL.io load/store + DMA semantics | CAL payloads, waveform-table uploads, calibration constants, raw-IQ capture readback | Standard CXL link-level replay |

Rationale for the RT no-retry rule **[Theoretical]**, grounded in physics: a control pulse delivered after its scheduled point in the coherence window is not "late data," it is a *different physical operation* applied to a state that has continued to evolve/decohere. Re-delivery can only corrupt the computation. The only correct behaviors are *discard and count* (§8) and, if drops persist, *resynchronize and re-execute the shot from the circuit description* — re-execution being the sole legitimate restore semantics for quantum work **[Proven]** (no-cloning; research doc §5.2).

---

## 4. Flit and Packet Format

### 4.1 Flit layout (256 B total)

Formalizing research doc §4.3:

| Region | Size | Contents |
|---|---|---|
| Header | 16 B | QCX transaction header (§4.2) |
| Payload | 224 B | Type-specific layout (§4.3) |
| CRC/FEC | 16 B | Link-level integrity (CXL 3.1 flit mechanism; §8) |
| **Total** | **256 B** | CXL 3.1 latency-optimized flit **[Demonstrated]** |

### 4.2 Header — byte-exact field table (16 B = 128 bits)

The four fields named by the research doc §4.3 (`type`, `vqid[16]`, `t_exec[64]`, `seq[32]`) are carried exactly; the remaining 16 bits (`chan`, `flags`, `plen`) are v0.1 packing additions **[Theoretical]**.

| Byte offset | Bits | Field | Width | Description |
|---|---|---|---|---|
| 0 | [7:4] | `type` | 4 b | `0x1` GATE, `0x2` PULSE, `0x3` MEAS, `0x4` SYNC, `0x5` CAL, `0x6` RESULT; `0x0`, `0x7–0xF` reserved |
| 0 | [3] | `chan` | 1 b | 0 = RT, 1 = BULK |
| 0 | [2:0] | `flags` | 3 b | bit 0 `SEG` (payload continues in next flit), bit 1 `SEG_END` (last segment), bit 2 reserved |
| 1 | [7:0] | `plen` | 8 b | Valid payload bytes, 0–224 |
| 2–3 | — | `vqid` | 16 b | Virtual qubit ID (host-side mapping); primary/base target of this flit |
| 4–7 | — | `seq` | 32 b | Shot / circuit sequence number |
| 8–15 | — | `t_exec` | 64 b | Execution timestamp, **ps resolution, global QCX epoch — time-triggered, not best-effort**. On upstream flits (RESULT, CAL) this field carries the *capture* timestamp |
| | | **Total** | **128 b = 16 B** | |

Multi-byte fields are little-endian (PCIe convention). The global QCX epoch is established and maintained by SYNC flits (§4.3.4).

### 4.3 Payload layouts per type **[Theoretical]**

#### 4.3.1 GATE — parameterized gate opcodes

Per research doc §4.2, QCX mandates **waveform caching at the QPU-side sequencer** (the approach of QICK, QubiC 2.0, and commercial controllers): the host sends parameterized gate opcodes, and the sequencer expands them locally into pulses. The GATE payload is a packed array of gate records:

**Base record — 10 B** (matches the research doc's ~10 B/gate serialization figure, §4.2):

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–1 | `opcode` | u16 | Gate opcode (table below); bit 15 = 0 |
| 2–3 | `target0` | u16 | Target vqid |
| 4–5 | `target1` | u16 | Second target vqid for two-qubit gates; `0xFFFF` = unused |
| 6–9 | `param0` | f32 | θ rotation parameter; 0.0 for non-parameterized gates |

**Extended record — 14 B**: `opcode` bit 15 set (`| 0x8000`) appends `param1` (f32, φ) for two-parameter gates.

A 224 B payload holds up to **22 base records** (220 B; `plen` bounds the valid bytes). Records are parsed sequentially; record size is determined by opcode bit 15.

**Opcode assignments** (QCX v0.1). Mnemonics follow the QISA-K instruction table — see [docs/research/02-quantum-linux.md](../../docs/research/02-quantum-linux.md), QISA table — so that the kernel-facing ISA and the bus encoding share one gate vocabulary; the 16-bit QCX encodings below are defined by this spec **[Theoretical]**:

| Opcode | Mnemonic (QISA-K) | Params | Notes |
|---|---|---|---|
| `0x0001` | `H` | — | Hadamard |
| `0x0002` | `X` | — | Pauli-X |
| `0x0003` | `Y` | — | Pauli-Y |
| `0x0004` | `Z` | — | Pauli-Z |
| `0x0005` | `S` | — | Phase π/2 |
| `0x0006` | `T` | — | Phase π/4 (non-Clifford resource) |
| `0x0007` | `RESET` | — | Active reset to \|0⟩ |
| `0x0010` | `RX(θ)` | θ | Continuous rotation |
| `0x0011` | `RY(θ)` | θ | Continuous rotation |
| `0x0012` | `RZ(θ)` | θ | Continuous rotation |
| `0x0020` | `CNOT` | — | `target0` = control, `target1` = target |
| `0x0021` | `CZ` | — | Native on most superconducting lattices |

QISA-K's `MEASURE` does not appear as a GATE record — measurement travels as a MEAS flit (§4.3.3). `FMR` and `QWAIT` are host-side / sequencer-timing concerns, not bus transactions.

#### 4.3.2 PULSE — cached-waveform playback descriptor

Raw waveform samples MUST NOT be carried on the RT channel (bandwidth analysis, §6). A PULSE record references a waveform previously uploaded via the BULK channel:

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–1 | `wave_id` | u16 | Waveform-cache table index (sequencer-local) |
| 2–3 | `ctrl_ch` | u16 | Physical control channel |
| 4–7 | `amp_scale` | f32 | Amplitude scale factor |
| 8–11 | `phase` | f32 | Phase offset (radians) |
| 12–15 | `duration_ns` | u32 | Playback window, ns |

16 B per record; up to 14 records per flit.

#### 4.3.3 MEAS — measurement command

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–1 | `base_vqid` | u16 | First qubit of the measured contiguous vqid range |
| 2–3 | `n_qubits` | u16 | Number of qubits measured |
| 4–5 | `window_id` | u16 | Readout integration-window descriptor (calibration store) |
| 6 | `mode` | u8 | 0 = discriminated (RESULT return), 1 = raw IQ (CAL return on BULK, calibration mode) |
| 7 | `rsvd` | u8 | Reserved |

#### 4.3.4 SYNC — timebase / epoch maintenance

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–3 | `epoch_id` | u32 | Epoch generation counter |
| 4–11 | `t_master` | u64 | Master epoch timestamp (ps) |
| 12–15 | `drift_ppb` | i32 | Measured drift, parts-per-billion |
| 16 | `action` | u8 | 0 = announce, 1 = resync request, 2 = resync acknowledge |

SYNC flits use `vqid = 0x0000` and have the highest arbitration priority (§7); the ps-resolution `t_exec` semantics of every other flit depend on epoch agreement.

#### 4.3.5 CAL — segmented raw IQ windows (BULK channel)

Research doc §4.3: "CAL payload: raw IQ window (segmented across flits)."

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–1 | `stream_id` | u16 | Capture stream identifier |
| 2–5 | `seg_off` | u32 | Byte offset of this segment within the stream |
| 6–9 | `total_len` | u32 | Total stream length (bytes) |
| 10–223 | `data` | ≤214 B | Raw IQ samples (i16 I/Q pairs); `SEG`/`SEG_END` header flags delimit the train |

#### 4.3.6 RESULT — measurement result (the research doc's "MEAS RESULT": bitmask + confidence + timestamp)

The capture timestamp rides in the header `t_exec` field (§4.2); the payload carries:

| Offset | Field | Width | Description |
|---|---|---|---|
| 0–1 | `base_vqid` | u16 | First qubit of the result range |
| 2–3 | `n_qubits` | u16 | Number of qubits reported |
| 4 … | `outcomes` | ⌈n/8⌉ B | Discriminated outcome bitmask, LSB = `base_vqid` |
| … | `confidence` | u8 × n | Per-qubit discrimination confidence, 0–255 |

O(1) byte per qubit per measurement, consistent with the research doc §4.2 return-path sizing.

---

## 5. Latency SLAs

### 5.1 Round-trip budget — research doc §4.1, reproduced line for line

The control loop that matters is: *measure qubits → move syndrome/result data to classical logic → decode/decide → apply conditioned pulses*. **[Theoretical]** budget, constrained by demonstrated anchors:

| Segment | Budget | Rationale |
|---|---|---|
| Readout digitization + DSP | 300–500 ns | demonstrated integration windows on RFSoC-class hardware |
| QCX transport (QPU-side ctrl → host) | ≤100 ns | feasible: CXL retimer pin-to-pin <12 ns **[Demonstrated]**; PCIe-class PHY traversal is ~100 ns-class |
| Host decode/branch (GPU/NPU kernel) | ≤1 µs | demonstrated within DGX Quantum envelope |
| QCX transport (return) + pulse trigger | ≤200 ns | symmetric path + sequencer dispatch |
| **Total** | **≤2 µs** | ~1% of a 200 µs T1; ~2 QEC cycles of slack |

Benchmarks: a 2 µs loop against T1 ≈ 200 µs gives a duty-cost of ~10⁻² of the coherence budget per branch — acceptable. The demonstrated state of the art is the NVIDIA DGX Quantum GPU↔QPU round trip at <4 µs, with **3.3 µs measured** **[Demonstrated]** (research doc §4.1); QCX targets the inside of that envelope. Against trapped-ion coherence (seconds-class **[Demonstrated]**) the constraint is trivial.

> **Queueing caveat [Proven]:** the binding case is superconducting QEC, where the decoder must keep pace with a ~1 µs syndrome cycle indefinitely or the backlog grows as Θ(t) (queueing argument: arrival rate exceeding service rate yields unbounded queue). The ≤1 µs host decode/branch line is therefore the single most fragile SLA in this table — a conforming host MUST sustain it continuously, not merely on average.

### 5.2 Per-traffic-class SLAs **[Theoretical]**

| Class | Flit types | Channel | Priority | Delivery SLA |
|---|---|---|---|---|
| Timebase | SYNC | RT | P0 (highest) | Bounded jitter; serviced ahead of all other traffic — every `t_exec` in the system depends on epoch agreement |
| Readout return | MEAS, RESULT | RT | P1 | Within the ≤100 ns QPU→host transport segment of §5.1 |
| Gate control | GATE, PULSE | RT | P2 | Within the ≤200 ns return-transport + pulse-trigger segment; the operation executes at `t_exec`, so arrival MUST precede `t_exec` or the flit is dropped (§8) |
| Bulk | CAL, waveform-table uploads | BULK | P3 (lowest) | Best-effort; ordinary CXL.io semantics; no real-time SLA |

---

## 6. Bandwidth Provisions

Requirement: **~10 GB/s sustained — a PCIe 5.0 x4-class envelope** **[Theoretical]**, derived as follows (research doc §4.2):

**Raw waveform streaming is explicitly ruled out.** Per superconducting qubit, direct-digital pulse synthesis uses DAC channels at ~1 GS/s effective per channel (RFSoC converters run 4–6.5 GS/s with interpolation) **[Demonstrated]**. Worst case: 1 GS/s × 16 bit × 2 (I/Q) ≈ 4 GB/s per drive channel → 50 qubits ≈ **0.2 TB/s**; 5,000 qubits ≈ **20 TB/s**. Streaming raw waveforms across the board is a non-starter at scale; a conforming host MUST NOT stream raw waveform samples on the RT channel.

**Gate-opcode model (mandated).** With waveform caching at the QPU-side sequencer, the host sends parameterized gate opcodes at **~10 B per gate** (§4.3.1 base record). Effective host→QPU need: ~10⁴ gates × 10 B per shot at 10³–10⁵ shots/s ≈ **1–10 GB/s** — within a PCIe 5.0 x4 envelope.

**Return path.** O(1) byte per qubit per measurement (discriminated, §4.3.6), or ~kB per qubit for raw IQ traces in calibration mode (CAL on BULK). Syndrome streams for 5,000 physical qubits at 1 MHz cycle rate ≈ **5 GB/s** — again x4-link-class.

**Conclusion (research doc §4.2):** QCX needs ~10 GB/s sustained, ~100 ns transport latency, and — the differentiator from PCIe/CXL — **deterministic, time-triggered delivery**. **[Theoretical]**

---

## 7. Arbitration **[Theoretical]**

QCX arbitration is **strict-priority within pre-reserved time windows**:

1. **Strict priority order:** `SYNC > MEAS/RESULT > GATE/PULSE > CAL/BULK` (the P0–P3 classes of §5.2). At any slot boundary the highest-priority eligible flit wins; BULK traffic uses only slots left unreserved by the RT schedule.
2. **Time-triggered slot reservation:** RT-channel flits are admitted only into slots pre-reserved against the sequencer timeline, keyed to `t_exec`. The host-side scheduler reserves slots when it compiles the shot schedule; a flit arriving at the arbiter without a matching reservation window is queued behind reserved traffic (BULK) or dropped if its `t_exec` becomes unreachable (RT, §8). At the provisioned ~10 GB/s, one 256 B flit occupies ≈26 ns of link time, which bounds the slot granularity.
3. **Precedent:** the reservation discipline follows TTEthernet / IEEE 802.1Qbv (TSN) time-aware shaping — cited as *precedent for the mechanism*, not as a demonstrated QCX result. No time-triggered transaction layer over a CXL PHY has been built (TRL 2; research doc §12).

---

## 8. Bus-Level Error Handling **[Theoretical]**

Each flit carries a 16 B CRC/FEC region (§4.1), using the CXL 3.1 latency-optimized flit's integrity mechanism **[Demonstrated]** (PCIe 6.x PAM4 + FEC adds only ns-class latency **[Demonstrated]**, research doc §2.2).

**RT channel:**

- A conforming endpoint **MUST NOT retransmit** an RT-channel flit. A late flit is a discarded flit plus an error counter — re-delivered pulses are physically meaningless after the coherence window (research doc §4.3).
- A flit that fails CRC/FEC, or whose `t_exec` has passed (or is unreachable given pipeline depth) at arrival, MUST be discarded and MUST increment **`qcx_rt_drop_count`** (surfaced to the OS via the Stage 4 sysfs tree under `/dev/qpu0`'s device node).
- On a drop, the device endpoint MAY raise a **SYNC resynchronization** (`action = 1`, §4.3.4); the host SHOULD treat persistent drops as shot-invalidating and re-execute the affected shot from the circuit description — the only legitimate restore semantics **[Proven]** (no-cloning, research doc §5.2).

**BULK channel:** standard CXL link-level replay applies; CAL segment trains are additionally end-to-end checked via `total_len`/`seg_off` accounting (§4.3.5).

> **Scope note:** bus-level CRC/FEC protects *classical control data only* — flit headers, opcodes, parameters, and result bits in transit. It is **unrelated to quantum error correction of qubit state**, which is the job of the QEC code running *through* this bus (syndrome measurement → decode → conditioned correction), not *on* it.

---

## 9. Comparison to Existing Approaches

Reproduced from research doc §4.4 so this spec stays benchmarked against demonstrated systems:

| Approach | Where classical control sits | Loop latency | Notes |
|---|---|---|---|
| IBM third-generation control electronics (System Two) | Room temperature, rack-scale, beside cryostat | µs-class internal; cloud users see ms–s | **[Demonstrated]** |
| NVIDIA DGX Quantum / Quantum Machines | Room temperature; Grace Hopper coupled to OPX controller | <4 µs GPU↔QPU round trip (3.3 µs shown) | **[Demonstrated]**; deployed at Jülich **[Demonstrated]** |
| SEEQC SFQ digital control | **Inside the cryostat at mK**, co-fabricated control | Pulse-level control without per-qubit coax to room temp; >99.5% fidelities maintained | **[Demonstrated]** |
| QCX (this work) | Board-level, time-triggered transaction layer over CXL-class PHY | ≤2 µs target | **[Theoretical]** |

QCX is best understood as standardizing the DGX-Quantum-style coupling into a board-level, vendor-neutral transaction layer — and, for superconducting systems, terminating at an SEEQC-style cryo-digital endpoint rather than at racks of coax (research doc §4.4).

---

## 10. Worked Example: One Gate-Dispatch Round Trip **[Theoretical]**

Scenario: a mid-circuit feed-forward correction on HybridBoard-SC. Four syndrome ancillas (`vqid 0x0028–0x002B`) are measured; the host GPU decodes the syndrome and dispatches a conditioned Pauli-`X` correction on data qubit `vqid 0x002A`, all within the ≤2 µs budget. Shot sequence number `seq = 123456` (`0x0001E240`). The readout window closes at `t_meas = 1,000,000,000,000 ps` (1.0 s) after the QCX epoch.

### 10.1 Timeline against the §5.1 budget

| t (rel. to readout close) | Event | Budget segment | Budget | Modeled |
|---|---|---|---|---|
| 0 ns | Readout integration complete; digitization + DSP discriminate 4 ancillas | Readout digitization + DSP | 300–500 ns | 420 ns |
| 420 ns | RESULT flit serialized; RT channel, QPU→host over ≤10 m optical (~50 ns fiber + serdes/retimer) | QCX transport (QPU-side ctrl → host) | ≤100 ns | 90 ns |
| 510 ns | GPU decoder kernel consumes syndrome from result ring buffer; decides `X` on `0x002A` | Host decode/branch | ≤1 µs | 800 ns |
| 1,310 ns | GATE flit dispatched; return transport + sequencer pulse trigger | QCX transport (return) + pulse trigger | ≤200 ns | 180 ns |
| 1,490 ns | Flit at sequencer; pulse armed for `t_exec` | — | — | (360 ns guard band) |
| **1,850 ns** | Correction pulse executes at `t_exec = t_meas + 1,850,000 ps` | **Total** | **≤2 µs** | **1.85 µs ✓** |

The host schedules `t_exec` 360 ns after worst-case flit arrival; if the flit were to arrive after `t_exec`, it would be discarded and counted in `qcx_rt_drop_count` — never retried (§8).

### 10.2 Upstream flit: RESULT (QPU → host, RT channel)

Header fields: `type = RESULT (0x6)`, `chan = RT (0)`, `flags = 0`, `plen = 9`, `vqid = 0x0028` (base of range), `seq = 0x0001E240`, `t_exec = capture timestamp = 0x000000E8D4A51000` (= 10¹² ps). Payload: `base_vqid = 0x0028`, `n_qubits = 4`, outcome bitmask `0b0010 = 0x02` (ancilla `0x0029` fired), confidence bytes `F0 E8 FA F1`.

```
Offset    Bytes                                            Field
------    -----------------------------------------------  ----------------------------
0x00      60                                               type=0x6 RESULT|chan=RT|flags=0
0x01      09                                               plen = 9
0x02      28 00                                            vqid = 0x0028 (LE)
0x04      40 E2 01 00                                      seq  = 0x0001E240 (LE)
0x08      00 10 A5 D4 E8 00 00 00                          t_exec = 0xE8D4A51000 ps (LE)
------    -----------------------------------------------  ---- payload (224 B) --------
0x10      28 00                                            base_vqid = 0x0028
0x12      04 00                                            n_qubits  = 4
0x14      02                                               outcomes  = 0b0010
0x15      F0 E8 FA F1                                      confidence[4] = 240,232,250,241
0x19      00 ... 00  (215 B zero pad; plen marks 9 valid)
------    -----------------------------------------------  ---- CRC/FEC (16 B) ---------
0xF0      [16 B CRC/FEC — computed by the CXL 3.1 link
           layer; opaque to the QCX transaction layer]
```

### 10.3 Downstream flit: GATE (host → QPU, RT channel)

Header fields: `type = GATE (0x1)`, `chan = RT (0)`, `flags = 0`, `plen = 10` (one base gate record), `vqid = 0x002A`, `seq = 0x0001E240`, `t_exec = 0x000000E8D4C14A90` (= 1,000,001,850,000 ps = `t_meas` + 1.85 µs). Payload: one 10 B base record — `opcode = 0x0002` (`X`, QISA-K mnemonic), `target0 = 0x002A`, `target1 = 0xFFFF` (unused), `param0 = 0.0f`.

```
Offset    Bytes                                            Field
------    -----------------------------------------------  ----------------------------
0x00      10                                               type=0x1 GATE|chan=RT|flags=0
0x01      0A                                               plen = 10
0x02      2A 00                                            vqid = 0x002A (LE)
0x04      40 E2 01 00                                      seq  = 0x0001E240 (LE)
0x08      90 4A C1 D4 E8 00 00 00                          t_exec = 0xE8D4C14A90 ps (LE)
------    -----------------------------------------------  ---- payload (224 B) --------
0x10      02 00                                            opcode  = 0x0002 (X)
0x12      2A 00                                            target0 = 0x002A
0x14      FF FF                                            target1 = unused
0x16      00 00 00 00                                      param0  = 0.0f
0x1A      00 ... 00  (214 B zero pad; plen marks 10 valid)
------    -----------------------------------------------  ---- CRC/FEC (16 B) ---------
0xF0      [16 B CRC/FEC — computed by the CXL 3.1 link
           layer; opaque to the QCX transaction layer]
```

The sequencer expands the `X` opcode into the cached, per-qubit-calibrated pulse for `vqid 0x002A` (waveform caching per §4.3.1/§6) and fires it when the global QCX epoch clock reaches `t_exec`. Round trip closed at 1.85 µs — inside the ≤2 µs budget, with the demonstrated 3.3 µs DGX Quantum loop **[Demonstrated]** as the external benchmark this target must beat to justify existing.

---

## 11. Open Issues (tracked in the workflow's Risks table)

| # | Issue | Tag |
|---|---|---|
| 1 | Should the RT channel expose per-flit FEC strength as a negotiable link parameter (latency vs drop-rate trade), or is fixed FEC + drop-counting sufficient? Revisit once any emulation data exists (workflow Risk #9). | **[Theoretical]** |
| 2 | Slot-reservation granularity (≈26 ns flit time at ~10 GB/s) vs sequencer timeline compilation — unvalidated; no time-triggered transaction layer over a CXL PHY has been built (workflow Risk #1). | **[Theoretical]** |
| 3 | The ≤1 µs host decode SLA is existential for the SC variant: a decoder slower than the ~1 µs syndrome cycle accrues Θ(t) backlog (workflow Risk #2). | **[Proven]** (queueing) / **[Theoretical]** (budget) |
