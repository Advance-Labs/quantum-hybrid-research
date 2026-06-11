; bell.qs -- uncorrected Bell pair: maximal two-qubit entanglement.
;
; This is the research doc's Bell listing with the FMR/BRN/X feed-forward
; path removed (docs/research/02-quantum-linux.md, QISA section; workflow
; Stage 2 step 8) -- instruction-for-instruction the same program as
; qcpu.BELL_UNCORRECTED_ASM and the worked example of
; quantum-linux/qos/QLOS-DESIGN-v0.1.md section 7. It is also the "Bell
; hello-world" the Stage 5 kernel-init harness submits through the QLOS
; runtime (emulator/test_kernel_init.py).
;
; PHYSICS
;   H       rotates q0 into the superposition (|0> + |1>)/sqrt(2).
;   CNOT    entangles q0 (control) with q1 (target):
;           (|00> + |11>)/sqrt(2) -- the Bell state. Neither qubit alone
;           has a definite value, yet their outcomes are perfectly
;           correlated.
;   MEASURE q0 collapses the PAIR (projective measurement on an entangled
;           state, [Proven]); the subsequent q1 measurement is then fully
;           determined by the c0 outcome.
;
; EXPECTED MEASUREMENT STATISTICS over N shots
;   c0 == c1 in EVERY shot            ('01' and '10' never occur)
;   marginal of c0 ~ 50/50            (binomial: sigma = sqrt(N)/2;
;                                      the test suite uses a 5-sigma window)
;   counts ~= {"00": N/2, "11": N/2}
        RESET   q0              ; active |0> preparation
        RESET   q1
        H       q0              ; q0 -> (|0> + |1>)/sqrt(2)
        CNOT    q0, q1          ; entangle: (|00> + |11>)/sqrt(2)
        MEASURE q0 -> c0        ; destructive: collapses the pair
        MEASURE q1 -> c1        ; outcome already determined by c0
