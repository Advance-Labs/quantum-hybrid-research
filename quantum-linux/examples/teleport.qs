; teleport.qs -- Bell pair with feed-forward: the inner loop of teleportation.
;
; The instruction body below is the research doc's QISA-K feed-forward
; listing verbatim (docs/research/02-quantum-linux.md, "Example: Bell pair
; with feed-forward in QISA-K"; same program as qcpu.BELL_FEEDFORWARD_ASM).
; It prepares a Bell pair, measures one half, and classically conditions a
; correction on the other -- the measure-and-correct (disentangling) step
; that quantum teleportation is built from, and the minimal program
; exercising every semantic class of the ISA: unitary (H, CNOT, X),
; non-unitary (RESET, MEASURE), classical transfer (FMR), classical control
; flow (BRN), and timing (QWAIT).
;
; PHYSICS
;   After H + CNOT the pair is (|00> + |11>)/sqrt(2). MEASURE q0 collapses
;   it: c0 = 0 leaves q1 in |0>, c0 = 1 leaves q1 in |1>. The classical
;   path FMR c0 -> r1; BRN r1, .skip then branches IF r1 IS NONZERO
;   (QISA-v0.1.yaml BRN semantics), so the X correction fires exactly on
;   the c0 == 0 branch. Both paths therefore steer q1 to the SAME basis
;   state |1>: the correction disentangles q1 from the measured half and
;   makes its value deterministic.
;
; EXPECTED MEASUREMENT STATISTICS over N shots
;   c1 == 1 in EVERY shot             (deterministic disentangled outcome)
;   marginal of c0 ~ 50/50            (the Bell collapse stays random)
;   c0 == c1 does NOT hold here       (unlike bell.qs -- do not assert it)
;
; FEED-FORWARD HONESTY (workflow Risk 3; design doc limitation 5): in the
; emulator the BRN branch executes in the ordinary instruction loop. On
; real hardware the measure -> branch -> X path must resolve INSIDE the
; coherence window of q1 and therefore lives in control firmware below any
; OS code path [Demonstrated] (eQASM; QNodeOS's real-time QNPU) -- Linux
; interrupt latency cannot meet those deadlines reliably.
;
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
