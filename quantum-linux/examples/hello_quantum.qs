; hello_quantum.qs -- QLOS "hello, world": deterministic |1> preparation.
;
; The first userland program of the normalized quantum dev loop
; (quantum-linux/qos/QLOS-DESIGN-v0.1.md, section 7):
;
;   edit      hello_quantum.qs                                  (this file)
;   assemble  python toolchain/qas.py hello_quantum.qs          ("cc")
;   run       python examples/qrun.py hello_quantum.qs --shots 1024 ("exec")
;
; PHYSICS
;   RESET   actively prepares |0> (measure + conditional X) -- non-unitary,
;           always physically allowed: it destroys state, never copies it.
;   X       is the Pauli bit-flip unitary: |0> -> |1>.
;   MEASURE projects q0 onto the Z basis and writes the outcome to shadow
;           register c0, destroying any superposition (measurement
;           postulate [Proven]). Here the pre-measurement state is the
;           basis state |1>, so the outcome is certain, not sampled.
;
; EXPECTED MEASUREMENT STATISTICS (any seed, any shot count)
;   c0 == 1 in 100% of shots          counts == {"1": shots}
;
; The QWAIT advances the emulator's cycle counter only (deterministic cycle
; alignment, eQASM-style); it is NOT a timing or decoherence model
; (workflow Risk 3). On real hardware idle cycles cost coherence,
; F(t) ~= e^(-t/T2) [Demonstrated] -- the emulator charges no such price.
        RESET   q0              ; active |0> preparation (non-unitary)
        QWAIT   8               ; deterministic cycle alignment (eQASM-style)
        X       q0              ; Pauli flip: |0> -> |1>
        MEASURE q0 -> c0        ; certain outcome: c0 = 1, every shot
