/*
 * quantum_scheduler.c — HybridBoard CPU/GPU/QPU workload routing reference model
 * =============================================================================
 *
 * STATUS: THEORETICAL REFERENCE MODEL — TRL 2. NO HARDWARE EXISTS.
 *
 * This file is a *paper design rendered as compilable C*, produced under
 * Stage 4 ("OS Driver Model") of docs/workflows/03-hybridboard-workflow.md.
 * It models the scheduling policy a Linux `qcx` bus driver would apply when
 * routing work between the classical complex (CPU, GPU) and a QCX-attached
 * QPU on the hypothetical HybridBoard platform described in
 * docs/research/03-hybrid-board.md. It is NOT a kernel module, NOT a driver,
 * and no code path communicates with real hardware (workflow Stage 4
 * acceptance criteria). It is written in kernel-flavored style (u32/u64,
 * pr_info, platform_driver shape per research doc §8.3) but compiles as
 * standalone C11: the #ifndef __KERNEL__ block below supplies compatibility
 * typedefs and stubs instead of including kernel headers, which do not — and
 * for QCX cannot yet — provide a real `qcx` bus.
 *
 * Grounding (every figure below is taken from the research doc; tags are
 * carried over verbatim and never promoted, per the workflow ground rules):
 *
 *  - Latency, not bandwidth, is the binding constraint: the QCX control loop
 *    must close in <= 2 us against superconducting T1 ~ 160-350 us
 *    [Demonstrated]; benchmarked vs the 3.3 us DGX Quantum GPU<->QPU round
 *    trip [Demonstrated]. See docs/research/03-hybrid-board.md §4.1.
 *  - A decoder slower than the ~1 us syndrome cycle accrues Theta(t) backlog
 *    [Proven] (queueing argument, §4.1) — hence the queue-depth admission
 *    check before any QPU routing decision.
 *  - Quantum state can never be checkpointed, paged, migrated, or mirrored:
 *    no-cloning + measurement collapse [Proven] (§5.2, Wootters & Zurek
 *    1982). Only re-executable circuit submissions are schedulable; this is
 *    ENFORCED below, not merely commented.
 *  - Shots are non-preemptible at microsecond granularity; the QPU queue is
 *    a real-time submission class (DPDK-style isolated-core pattern, §8.3).
 *  - The algorithmic case for QPU routing is narrow and honestly tagged
 *    (§9.2): QEC decode and variational/calibration inner loops are the only
 *    demonstrated us-class need [Demonstrated]; Shor is a [Proven] separation
 *    vs *best-known* classical; Grover's quadratic gain is erased by
 *    constants at consumer scale [Theoretical]; HHL carries state-prep /
 *    condition-number / readout fine print [Theoretical].
 *
 * Build (workflow Stage 4, step 4 — userspace compile-check only):
 *   cc -std=c11 -fsyntax-only quantum_scheduler.c            # syntax check
 *   cc -std=c11 -Wall -Wextra -Werror -DQSCHED_DEMO \
 *      -o /tmp/qsched quantum_scheduler.c -lm && /tmp/qsched # routing demo
 *
 * Copyright: Advance Labs quantum/classical hybrid research series.
 * Document of record: docs/research/03-hybrid-board.md (June 2026).
 */

/* ------------------------------------------------------------------------ *
 * Kernel-compatibility shim.
 *
 * In a real kernel tree these names come from <linux/types.h>,
 * <linux/printk.h>, and <linux/platform_device.h>. No such tree can host a
 * `qcx` bus today (research doc §12: QCX is TRL 2, "concept formulated; no
 * implementation"), so when built standalone we supply minimal stand-ins.
 * This is deliberate per the project spec: stubs instead of kernel headers,
 * so the file passes `cc -fsyntax-only` as plain C11.
 * ------------------------------------------------------------------------ */
#ifndef __KERNEL__

#include <assert.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

/* M_PI / M_E are POSIX extensions, not ISO C11: glibc hides them under
 * -std=c11 (strict ISO mode), while Darwin's math.h exposes them. Define
 * the portable fallbacks so the file builds with any conforming compiler. */
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_E
#define M_E 2.71828182845904523536
#endif

/* <linux/types.h> equivalents. */
typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int32_t  s32;
typedef int64_t  s64;

/* <linux/printk.h> equivalent: route kernel-style logging to stdout. */
#define pr_info(...)  ((void)printf(__VA_ARGS__))
#define pr_warn(...)  ((void)fprintf(stderr, __VA_ARGS__))

/* <linux/platform_device.h> skeletal equivalents — shape only, so the
 * driver-model sketch at the bottom of this file stays idiomatic against
 * research doc §8.3 ("a `qcx` bus driver modeled on the PCIe/CXL core"). */
struct platform_device {
	const char *name;
};
struct platform_driver {
	int (*probe)(struct platform_device *pdev);
	int (*remove)(struct platform_device *pdev);
	const char *name;
	const char *acpi_match; /* stand-in for real ACPI match tables */
};

#define QSCHED_BUG_ON(cond) assert(!(cond))

/* The public surface of this reference model is consumed by the optional
 * -DQSCHED_DEMO main(); when built without it (e.g. `cc -fsyntax-only`)
 * these statics are intentionally unreferenced. */
#define QSCHED_API static __attribute__((unused))

#endif /* !__KERNEL__ */

/* ------------------------------------------------------------------------ *
 * Platform constants — every value cites docs/research/03-hybrid-board.md.
 * ------------------------------------------------------------------------ */

/* §4.1: QCX round-trip latency budget, total <= 2 us (2000 ns). */
#define QCX_LOOP_BUDGET_NS        2000ULL
/* §4.1: budget line items (readout DSP 300-500 ns; transport <=100 ns;
 * host decode/branch <=1 us; return + pulse trigger <=200 ns). */
#define QCX_READOUT_DSP_MAX_NS     500ULL
#define QCX_TRANSPORT_MAX_NS       100ULL
#define QCX_HOST_DECODE_MAX_NS    1000ULL
#define QCX_RETURN_TRIGGER_MAX_NS  200ULL
/* §4.1: superconducting T1 window, 160-350 us [Demonstrated]; we budget
 * against the 200 us reference figure used in the doc's duty-cost argument
 * ("a 2 us loop against T1 ~ 200 us gives a duty-cost of ~1e-2"). */
#define QPU_T1_REFERENCE_NS     200000ULL
/* §4.1: QEC syndrome cycle cadence ~1 us [Demonstrated, Google Willow]. A
 * service rate below this arrival rate yields Theta(t) backlog [Proven]. */
#define QEC_SYNDROME_CYCLE_NS     1000ULL
/* §4.2: sustained QCX bandwidth need ~10 GB/s; ~10 bytes per gate opcode
 * with waveform caching at the sequencer [Theoretical]. */
#define QCX_BYTES_PER_GATE          10ULL
/* Queue-depth admission limit for the real-time QPU class. With a ~1 us
 * service cycle (§4.1), a depth-64 queue bounds added latency at ~64 us —
 * still inside the T1 window but a third of it; deeper queues would let
 * backlog consume the coherence budget, so we refuse admission instead
 * (model parameter; the *need* for the bound is the [Proven] queueing
 * argument, the specific constant is ours). */
#define QPU_QUEUE_DEPTH_MAX         64U

/* §9.2 / workflow Stage 4: Grover's Theta(sqrt(N)) [Proven] gain is erased
 * by constant-factor overheads at consumer scale [Theoretical]. The research
 * doc states the erasure without fixing a number, so this multiplier is an
 * ILLUSTRATIVE model constant (error-corrected quantum query vs classical
 * probe cost ratio), chosen only to make the crossover visible in the demo:
 * quantum wins only when sqrt(N) * OVERHEAD < N, i.e. N > OVERHEAD^2. */
#define GROVER_QUANTUM_OVERHEAD   1.0e6

/* HHL polylog condition-number guard (research doc §9.2: "condition number
 * kappa growing at most polylogarithmically"). We instantiate the guard as
 * kappa <= (log2 N)^2 — the doc fixes the *form* (polylog), the exponent 2
 * is a model choice and is labeled as such. [Theoretical] */
static inline double hhl_kappa_polylog_bound(u64 n)
{
	const double lg = log2((double)(n > 1 ? n : 2));
	return lg * lg;
}

/* ------------------------------------------------------------------------ *
 * Workload descriptor (workflow Stage 4, step 2).
 * ------------------------------------------------------------------------ */

enum compute_target {
	TARGET_CPU,
	TARGET_GPU,
	TARGET_QPU,
};

/* Workload op classes. The first four are the only classes the heuristic
 * will even *consider* for the QPU (linear algebra at scale, optimization
 * inner loops, crypto-class period finding, QEC service loops); everything
 * else is classical by construction (workflow Stage 4, step 3). */
enum workload_class {
	WL_QEC_DECODE_LOOP,      /* QEC decode-feedback inner loop          */
	WL_VARIATIONAL_INNER,    /* VQE/QAOA/calibration inner loop (opt.)  */
	WL_PERIOD_FINDING,       /* Shor-class crypto period finding        */
	WL_SPARSE_LINEAR_SOLVE,  /* HHL-class sparse linear system          */
	WL_DENSE_LINEAR_ALGEBRA, /* dense GEMM / factorization              */
	WL_UNSTRUCTURED_SEARCH,  /* Grover-shaped search                    */
	WL_IO_BOUND,             /* storage / network bound                 */
	WL_MEMORY_BOUND,         /* bandwidth-bound classical work          */
};

/* Numeric precision requested by the caller. Quantum amplitude estimates
 * are shot-noise limited; a workload demanding exact/f64 *output* from a
 * sampled observable is mis-specified for the QPU (§9.2 HHL fine print:
 * "only O(n) bits per shot are readable — not the full solution vector"). */
enum precision_class {
	PREC_SAMPLED,  /* accepts a sampled/estimated observable */
	PREC_F32,
	PREC_F64,
	PREC_EXACT,
};

struct workload_desc {
	const char         *name;        /* human-readable label (demo)      */
	enum workload_class wclass;      /* op class                         */
	u64                 n;           /* problem size N                   */
	double              sparsity_s;  /* s: nonzeros/row (HHL guard)      */
	double              kappa;       /* condition number (HHL guard)     */
	u32                 shots;       /* required shots per estimate      */
	u64                 gate_count;  /* transpiled gate budget estimate  */
	enum precision_class precision;  /* output precision demanded        */
	u64                 deadline_ns; /* per-iteration latency deadline   */
	bool coherence_fit;              /* circuit depth fits the coherence
	                                  * window of the attached QPU
	                                  * (transpiler-computed; §4.1)      */
	bool efficient_state_prep;       /* |b> preparable in polylog time
	                                  * (HHL guard #1, §9.2)             */
	bool requires_checkpoint;        /* job needs suspend/migrate — if
	                                  * true the QPU is PHYSICALLY
	                                  * impossible: no-cloning [Proven]
	                                  * (§5.2)                           */
};

/* Routing decision with the rationale carried alongside, so the policy is
 * auditable (the scheduler is "a model of policy, not of benefit" —
 * workflow Risks table, row 5). */
struct routing_decision {
	enum compute_target target;
	const char         *reason;
};

/* Scheduler state: the three submission queues of research doc §8.3 (one
 * io_uring-style ring per target behind /dev/qpu0 for the QPU). Pure model:
 * depths are counters, nothing is executed. */
struct qsched_state {
	u32 cpu_queue_depth;
	u32 gpu_queue_depth;
	u32 qpu_queue_depth;   /* real-time class; bounded, non-preemptible */
	u64 qcx_rt_drop_count; /* late-flit drop counter (§4.3: a late flit
	                        * is discarded, never re-delivered)         */
};

/* ------------------------------------------------------------------------ *
 * Cost models (research doc §9.2 — constant factors and complexity forms
 * are the doc's; where the doc gives only an asymptotic form, the
 * instantiated constant is labeled as a model choice).
 * ------------------------------------------------------------------------ */

/**
 * shor_quantum_gate_cost() - Quantum gate count for n-bit factoring.
 *
 * §9.2: "Shor factors n-bit integers in poly(n) — roughly
 * O(n^2 log n log log n) quantum gates" [Proven] (runtime; separation is
 * vs best-known classical, not a proven classical lower bound).
 */
static double shor_quantum_gate_cost(u64 n_bits)
{
	const double n = (double)(n_bits > 2 ? n_bits : 3);
	return n * n * log(n) * log(log(n) > 1.0 ? log(n) : M_E);
}

/**
 * nfs_classical_op_cost() - Best-known classical factoring cost.
 *
 * §9.2: number field sieve at exp(O(n^{1/3} (log n)^{2/3})) (itself
 * heuristic). The doc fixes only the asymptotic form; the prefactor
 * (64/9)^{1/3} ~= 1.923 is the conventional GNFS constant, supplied here
 * as a model instantiation. Returned in log-space (natural log of op
 * count) to avoid overflow at cryptographic sizes.
 */
QSCHED_API double nfs_classical_log_cost(u64 n_bits)
{
	const double n = (double)(n_bits > 2 ? n_bits : 3);
	const double c = 1.923; /* (64/9)^(1/3), conventional GNFS constant */
	return c * cbrt(n) * pow(log(n), 2.0 / 3.0);
}

/**
 * grover_quantum_cost() / grover_classical_cost() - Unstructured search.
 *
 * §9.2: Grover is Theta(sqrt(N)) vs classical Theta(N) [Proven] — "a
 * quadratic speedup that constant-factor overheads erase at consumer
 * scale" [Theoretical]. The quantum side is multiplied by
 * GROVER_QUANTUM_OVERHEAD (illustrative constant, see definition above)
 * so the model reproduces the erasure rather than hiding it.
 */
static double grover_quantum_cost(u64 n)
{
	return (M_PI / 4.0) * sqrt((double)n) * GROVER_QUANTUM_OVERHEAD;
}

static double grover_classical_cost(u64 n)
{
	return (double)n / 2.0; /* expected probes, Theta(N) [Proven] */
}

/**
 * hhl_quantum_cost() - HHL sparse linear-system solve cost.
 *
 * §9.2: O(log(N) * s^2 * kappa^2 / eps) [Theoretical] — valid ONLY under
 * the fine print enforced in qsched_classify(): efficient |b> preparation,
 * kappa at most polylog, sparsity s, and sampled-observable output
 * (Harrow-Hassidim-Lloyd; Aaronson's caveat analysis).
 */
QSCHED_API double hhl_quantum_cost(u64 n, double s, double kappa, double eps)
{
	return log2((double)(n > 1 ? n : 2)) * s * s * kappa * kappa / eps;
}

/**
 * cg_classical_cost() - Classical conjugate-gradient comparison point.
 *
 * §9.2: O(N * s * kappa * log(1/eps)).
 */
QSCHED_API double cg_classical_cost(u64 n, double s, double kappa, double eps)
{
	return (double)n * s * kappa * log(1.0 / eps);
}

/* ------------------------------------------------------------------------ *
 * Admission checks shared by all QPU-candidate branches.
 * ------------------------------------------------------------------------ */

/**
 * qsched_coherence_budget_ok() - Per-branch coherence-budget admission.
 *
 * §4.1: the control loop must close well inside the coherence window. We
 * admit a QPU candidate only if (a) the transpiler reported the circuit
 * fits the coherence window (w->coherence_fit), and (b) the caller's
 * per-iteration deadline can absorb at least one full <=2 us QCX loop —
 * a deadline tighter than the loop budget is physically unmeetable
 * [Theoretical] (budget) anchored on the 3.3 us DGX Quantum demonstration
 * [Demonstrated].
 */
static bool qsched_coherence_budget_ok(const struct workload_desc *w)
{
	if (!w->coherence_fit)
		return false;
	if (w->deadline_ns != 0 && w->deadline_ns < QCX_LOOP_BUDGET_NS)
		return false;
	return true;
}

/**
 * qsched_qpu_queue_ok() - Queue-depth admission for the real-time class.
 *
 * §4.1 [Proven]: arrival rate exceeding service rate yields an unbounded
 * (Theta(t)) queue. Rather than let backlog eat the coherence budget, the
 * scheduler refuses QPU admission past QPU_QUEUE_DEPTH_MAX and falls back
 * to the classical complex.
 */
static bool qsched_qpu_queue_ok(const struct qsched_state *st)
{
	return st->qpu_queue_depth < QPU_QUEUE_DEPTH_MAX;
}

/* ------------------------------------------------------------------------ *
 * The routing heuristic (workflow Stage 4, step 3 — implemented branch for
 * branch, with the research doc's honesty baked in as code, not vibes).
 * ------------------------------------------------------------------------ */

/**
 * qsched_classify() - Route a workload to CPU, GPU, or QPU.
 * @w:  workload descriptor (never modified).
 * @st: current scheduler state (queue depths; never modified here).
 *
 * Policy summary (workflow doc, Stage 4): linear algebra at scale /
 * optimization inner loops / crypto period finding are QPU *candidates*,
 * subject to coherence-budget and queue-depth checks; everything else is
 * CPU/GPU. Each branch cites its research-doc grounding.
 */
QSCHED_API struct routing_decision qsched_classify(const struct workload_desc *w,
					       const struct qsched_state *st)
{
	struct routing_decision d;

	/* --- Universal exclusion, checked FIRST and unconditionally. ---
	 * §5.2 [Proven]: no-cloning + measurement collapse make quantum
	 * checkpoint/suspend/migration physically impossible. A workload
	 * that requires checkpointing can NEVER be a QPU candidate, whatever
	 * its op class. This is the enforced form of workflow Risk #6. */
	if (w->requires_checkpoint) {
		d.target = (w->wclass == WL_DENSE_LINEAR_ALGEBRA) ?
			   TARGET_GPU : TARGET_CPU;
		d.reason = "requires checkpoint/migration -> quantum state "
			   "cannot be saved [Proven, no-cloning, S5.2]; "
			   "classical only";
		return d;
	}

	switch (w->wclass) {
	case WL_QEC_DECODE_LOOP:
		/* §4.1 + §9.2 [Demonstrated]: QEC decode-feedback is one of
		 * only two workloads with a demonstrated us-class need.
		 * It exists only in service of the QPU — but admission still
		 * gates on the queue bound: a decode loop that cannot keep
		 * the ~1 us syndrome cadence accrues Theta(t) backlog
		 * [Proven] and must be refused, not queued deeper. */
		if (!qsched_coherence_budget_ok(w)) {
			d.target = TARGET_GPU;
			d.reason = "QEC loop misses coherence budget "
				   "(<=2 us, S4.1) -> decode offline on GPU";
			return d;
		}
		if (!qsched_qpu_queue_ok(st)) {
			d.target = TARGET_GPU;
			d.reason = "QPU RT queue at bound -> refusing "
				   "admission (Theta(t) backlog otherwise "
				   "[Proven, S4.1]); GPU decode fallback";
			return d;
		}
		d.target = TARGET_QPU;
		d.reason = "QEC decode-feedback inner loop: demonstrated "
			   "us-class need [Demonstrated, S4.1/S9.2]";
		return d;

	case WL_VARIATIONAL_INNER:
		/* §9.2 [Demonstrated]: variational/calibration inner loops
		 * are the other demonstrated us-class hybrid workload (the
		 * DGX Quantum sell). Optimization-class QPU candidate. */
		if (!qsched_coherence_budget_ok(w)) {
			d.target = TARGET_GPU;
			d.reason = "variational loop fails coherence-budget "
				   "check (S4.1) -> classical optimizer step";
			return d;
		}
		if (!qsched_qpu_queue_ok(st)) {
			d.target = TARGET_CPU;
			d.reason = "QPU RT queue at bound -> defer iteration "
				   "to CPU-side optimizer [Proven queueing "
				   "argument, S4.1]";
			return d;
		}
		d.target = TARGET_QPU;
		d.reason = "variational/calibration inner loop: demonstrated "
			   "us-class need [Demonstrated, S9.2]";
		return d;

	case WL_PERIOD_FINDING:
		/* §9.2 [Proven] (narrow): Shor's poly(n) gate count vs the
		 * best-known (heuristic) classical NFS. Crypto-class QPU
		 * candidate — admitted only when the transpiled gate budget
		 * fits the machine AND the standard admission checks pass.
		 * The separation is vs best-known classical, not a proven
		 * classical lower bound (doc's own caveat, carried here). */
		if (w->gate_count > 0 &&
		    (double)w->gate_count < shor_quantum_gate_cost(w->n) ) {
			d.target = TARGET_CPU;
			d.reason = "declared gate budget below Shor cost "
				   "model O(n^2 log n log log n) [Proven, "
				   "S9.2] -> machine too small; classical";
			return d;
		}
		if (!qsched_coherence_budget_ok(w) || !qsched_qpu_queue_ok(st)) {
			d.target = TARGET_CPU;
			d.reason = "period finding fails coherence/queue "
				   "admission (S4.1) -> classical NFS path";
			return d;
		}
		d.target = TARGET_QPU;
		d.reason = "Shor-class period finding within gate budget: "
			   "[Proven] separation vs best-known classical "
			   "exp(O(n^1/3 (log n)^2/3)) [S9.2]";
		return d;

	case WL_SPARSE_LINEAR_SOLVE: {
		/* §9.2 [Theoretical]: HHL O(log N * s^2 * kappa^2 / eps) vs
		 * CG O(N * s * kappa * log(1/eps)) — linear algebra at scale
		 * is a QPU candidate ONLY behind the full fine-print guard
		 * set (Harrow-Hassidim-Lloyd + Aaronson caveats):
		 *   1. efficient |b> state preparation;
		 *   2. kappa at most polylog in N;
		 *   3. bounded sparsity s;
		 *   4. caller accepts a sampled observable, NOT the full
		 *      solution vector (only O(n) bits per shot readable).
		 */
		const double kappa_bound = hhl_kappa_polylog_bound(w->n);

		if (!w->efficient_state_prep) {
			d.target = TARGET_GPU;
			d.reason = "HHL guard fail: no efficient |b> prep "
				   "[Theoretical fine print, S9.2] -> GPU";
			return d;
		}
		if (w->kappa > kappa_bound) {
			d.target = TARGET_GPU;
			d.reason = "HHL guard fail: kappa exceeds polylog "
				   "bound (S9.2 'kappa at most polylog') "
				   "-> GPU iterative solver";
			return d;
		}
		if (w->sparsity_s * w->sparsity_s >= (double)w->n) {
			d.target = TARGET_GPU;
			d.reason = "HHL guard fail: insufficient sparsity, "
				   "s^2 term dominates [S9.2] -> GPU";
			return d;
		}
		if (w->precision != PREC_SAMPLED) {
			d.target = TARGET_GPU;
			d.reason = "HHL guard fail: caller demands full "
				   "solution vector / exact precision; only "
				   "O(n) bits per shot are readable "
				   "[Theoretical, S9.2] -> GPU";
			return d;
		}
		if (!qsched_coherence_budget_ok(w) || !qsched_qpu_queue_ok(st)) {
			d.target = TARGET_GPU;
			d.reason = "HHL candidate fails coherence/queue "
				   "admission (S4.1) -> GPU";
			return d;
		}
		d.target = TARGET_QPU;
		d.reason = "HHL-class solve, ALL guards hold (state prep, "
			   "polylog kappa, sparsity, sampled readout) "
			   "[Theoretical, S9.2]";
		return d;
	}

	case WL_DENSE_LINEAR_ALGEBRA:
		/* Workflow Stage 4: dense linear algebra stays classical —
		 * the GPU (MI300X-class, 5.3 TB/s HBM3 [Demonstrated, S2.1])
		 * is the right engine; no quantum speedup applies without
		 * the HHL sparsity structure. */
		d.target = TARGET_GPU;
		d.reason = "dense GEMM-class: stays classical on GPU "
			   "[Demonstrated HW, S2.1]; no applicable quantum "
			   "separation";
		return d;

	case WL_UNSTRUCTURED_SEARCH:
		/* §9.2: Grover Theta(sqrt(N)) [Proven], but constants erase
		 * the quadratic gain at consumer scale [Theoretical]. The
		 * cost model makes the erasure explicit. */
		if (grover_quantum_cost(w->n) < grover_classical_cost(w->n) &&
		    qsched_coherence_budget_ok(w) && qsched_qpu_queue_ok(st)) {
			d.target = TARGET_QPU;
			d.reason = "search at extreme N where sqrt(N) "
				   "survives modeled overheads [Theoretical "
				   "crossover, S9.2]";
			return d;
		}
		d.target = TARGET_CPU;
		d.reason = "Grover quadratic gain erased by constant-factor "
			   "overheads at this N [Proven asymptotics, "
			   "Theoretical erasure, S9.2] -> CPU/GPU";
		return d;

	case WL_IO_BOUND:
		d.target = TARGET_CPU;
		d.reason = "I/O-bound: classical by construction (workflow "
			   "Stage 4); no quantum I/O channel exists";
		return d;

	case WL_MEMORY_BOUND:
		d.target = TARGET_GPU;
		d.reason = "memory-bandwidth-bound: HBM3-class GPU memory "
			   "[Demonstrated, S2.1]; quantum registers are not "
			   "addressable memory [Proven, S5.2]";
		return d;
	}

	/* Unreachable with a well-formed enum; defensive default. */
	d.target = TARGET_CPU;
	d.reason = "unknown class -> conservative CPU default";
	return d;
}

/* ------------------------------------------------------------------------ *
 * Submission stubs (workflow Stage 4, step 2: "qsched_submit() stubs
 * modeling the three queues"). Counters only — nothing executes.
 * ------------------------------------------------------------------------ */

/**
 * qsched_submit() - Enqueue a routed workload on its target queue (model).
 * @w:  the workload (must have been classified).
 * @d:  routing decision from qsched_classify().
 * @st: scheduler state to update.
 *
 * Returns 0 on (modeled) success, -1 on refused admission.
 *
 * Enforced invariants (not just comments — workflow acceptance criteria):
 *  - QPU shots are non-preemptible at us granularity (§8.3): there is no
 *    preemption hook on the QPU path, and the RT-class depth bound is
 *    asserted here as a hard invariant.
 *  - No checkpointable job may reach the QPU queue [Proven, §5.2]:
 *    asserted, because qsched_classify() must already have excluded it.
 */
QSCHED_API int qsched_submit(const struct workload_desc *w,
			 const struct routing_decision *d,
			 struct qsched_state *st)
{
	switch (d->target) {
	case TARGET_CPU:
		st->cpu_queue_depth++;
		return 0;
	case TARGET_GPU:
		st->gpu_queue_depth++;
		return 0;
	case TARGET_QPU:
		/* [Proven, S5.2]: classifier must never route a
		 * checkpoint-requiring job here. Hard invariant. */
		QSCHED_BUG_ON(w->requires_checkpoint);
		/* Queue bound is an admission invariant, not advice
		 * ([Proven] Theta(t) backlog otherwise, S4.1). */
		QSCHED_BUG_ON(st->qpu_queue_depth >= QPU_QUEUE_DEPTH_MAX);
		/* Non-preemptible RT class: enqueue is the ONLY operation;
		 * no preempt/suspend/migrate entry points exist (S8.3). */
		st->qpu_queue_depth++;
		return 0;
	}
	return -1;
}

/* ------------------------------------------------------------------------ *
 * Driver-model sketch (research doc §8.3) — SHAPE ONLY.
 *
 * In a real (future) kernel tree, the scheduler above would sit behind a
 * platform_driver binding on the ACPI QDEV _HID "QCX0001" (research doc
 * §8.2), exposing /dev/qpu0 with an io_uring-style submission ring. The
 * stub below exists to keep the file honest about where the policy would
 * live; probe() does nothing because there is no hardware to probe — QCX
 * endpoints are TRL 2 (§12).
 * ------------------------------------------------------------------------ */

static int qcx_sched_probe(struct platform_device *pdev)
{
	pr_info("qcx-sched: probe(%s) — theoretical model; no QCX hardware "
		"exists (TRL 2, research doc S12)\n",
		pdev && pdev->name ? pdev->name : "qcx0");
	return 0;
}

static int qcx_sched_remove(struct platform_device *pdev)
{
	(void)pdev;
	return 0;
}

static struct platform_driver qcx_sched_driver __attribute__((unused)) = {
	.probe      = qcx_sched_probe,
	.remove     = qcx_sched_remove,
	.name       = "qcx-sched",
	.acpi_match = "QCX0001", /* ACPI QDEV _HID, research doc S8.2 */
};

/* ------------------------------------------------------------------------ *
 * Demo entry point: route a static workload table and print decisions.
 * Build with -DQSCHED_DEMO (workflow Stage 4, step 4). Covers every case
 * the workflow acceptance criteria require.
 * ------------------------------------------------------------------------ */
#ifdef QSCHED_DEMO

static const char *target_name(enum compute_target t)
{
	switch (t) {
	case TARGET_CPU: return "CPU";
	case TARGET_GPU: return "GPU";
	case TARGET_QPU: return "QPU";
	}
	return "???";
}

int main(void)
{
	/* Static demo table. Each row exercises one heuristic branch; the
	 * expected targets mirror the workflow Stage 4 acceptance list. */
	static const struct workload_desc table[] = {
		{ .name = "QEC decode-feedback loop",
		  .wclass = WL_QEC_DECODE_LOOP, .n = 5000, .shots = 0,
		  .gate_count = 0, .precision = PREC_SAMPLED,
		  .deadline_ns = QEC_SYNDROME_CYCLE_NS * 2,
		  .coherence_fit = true, .efficient_state_prep = false,
		  .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "VQE inner loop (chemistry)",
		  .wclass = WL_VARIATIONAL_INNER, .n = 64, .shots = 4096,
		  .gate_count = 20000, .precision = PREC_SAMPLED,
		  .deadline_ns = 50000, .coherence_fit = true,
		  .efficient_state_prep = true, .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "Dense GEMM 32768^2",
		  .wclass = WL_DENSE_LINEAR_ALGEBRA, .n = 32768ULL * 32768ULL,
		  .shots = 0, .gate_count = 0, .precision = PREC_F32,
		  .deadline_ns = 0, .coherence_fit = false,
		  .efficient_state_prep = false, .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "Unstructured search, consumer N=1e9",
		  .wclass = WL_UNSTRUCTURED_SEARCH, .n = 1000000000ULL,
		  .shots = 1, .gate_count = 0, .precision = PREC_SAMPLED,
		  .deadline_ns = 0, .coherence_fit = true,
		  .efficient_state_prep = false, .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "HHL candidate, kappa blows polylog guard",
		  .wclass = WL_SPARSE_LINEAR_SOLVE, .n = 1ULL << 30,
		  .shots = 100000, .gate_count = 0, .precision = PREC_SAMPLED,
		  .deadline_ns = 0, .coherence_fit = true,
		  .efficient_state_prep = true, .requires_checkpoint = false,
		  .sparsity_s = 4.0, .kappa = 1.0e5 },

		{ .name = "HHL candidate, all guards hold",
		  .wclass = WL_SPARSE_LINEAR_SOLVE, .n = 1ULL << 30,
		  .shots = 100000, .gate_count = 0, .precision = PREC_SAMPLED,
		  .deadline_ns = 100000, .coherence_fit = true,
		  .efficient_state_prep = true, .requires_checkpoint = false,
		  .sparsity_s = 4.0, .kappa = 100.0 },

		{ .name = "Shor period finding, RSA-2048, in budget",
		  .wclass = WL_PERIOD_FINDING, .n = 2048, .shots = 1,
		  .gate_count = 500000000ULL, .precision = PREC_SAMPLED,
		  .deadline_ns = 0, .coherence_fit = true,
		  .efficient_state_prep = false, .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "Long-running sim needing checkpoints",
		  .wclass = WL_VARIATIONAL_INNER, .n = 128, .shots = 8192,
		  .gate_count = 40000, .precision = PREC_SAMPLED,
		  .deadline_ns = 50000, .coherence_fit = true,
		  .efficient_state_prep = true, .requires_checkpoint = true,
		  .sparsity_s = 0.0, .kappa = 0.0 },

		{ .name = "Shot archive ETL (NVMe -> object store)",
		  .wclass = WL_IO_BOUND, .n = 0, .shots = 0, .gate_count = 0,
		  .precision = PREC_EXACT, .deadline_ns = 0,
		  .coherence_fit = false, .efficient_state_prep = false,
		  .requires_checkpoint = false,
		  .sparsity_s = 0.0, .kappa = 0.0 },
	};
	struct qsched_state st = { 0, 0, 0, 0 };
	size_t i;

	pr_info("HybridBoard quantum_scheduler — THEORETICAL reference model "
		"(TRL 2)\n");
	pr_info("Grounding: docs/research/03-hybrid-board.md S4.1/S5.2/S8.3/"
		"S9.2; workflow Stage 4.\n");
	pr_info("QCX loop budget: <=%llu ns vs T1 ref %llu ns "
		"[Demonstrated anchors]\n\n",
		(unsigned long long)QCX_LOOP_BUDGET_NS,
		(unsigned long long)QPU_T1_REFERENCE_NS);
	pr_info("%-44s %-6s %s\n", "WORKLOAD", "TARGET", "REASON");
	pr_info("%-44s %-6s %s\n", "--------", "------", "------");

	for (i = 0; i < sizeof(table) / sizeof(table[0]); i++) {
		const struct routing_decision d =
			qsched_classify(&table[i], &st);
		if (qsched_submit(&table[i], &d, &st) != 0)
			pr_warn("submit refused: %s\n", table[i].name);
		pr_info("%-44s %-6s %s\n", table[i].name,
			target_name(d.target), d.reason);
	}

	pr_info("\nQueue depths (modeled): CPU=%u GPU=%u QPU=%u (bound %u); "
		"qcx_rt_drop_count=%llu\n",
		st.cpu_queue_depth, st.gpu_queue_depth, st.qpu_queue_depth,
		QPU_QUEUE_DEPTH_MAX,
		(unsigned long long)st.qcx_rt_drop_count);
	pr_info("Cost-model spot checks (S9.2 forms):\n");
	pr_info("  Shor gates(n=2048)        ~ %.3e  [Proven form]\n",
		shor_quantum_gate_cost(2048));
	pr_info("  ln NFS ops(n=2048)        ~ %.1f   [best-known classical]\n",
		nfs_classical_log_cost(2048));
	pr_info("  Grover q-cost(N=1e9)      ~ %.3e vs classical %.3e "
		"[constants erase sqrt(N)]\n",
		grover_quantum_cost(1000000000ULL),
		grover_classical_cost(1000000000ULL));
	pr_info("  HHL(N=2^30,s=4,k=100)     ~ %.3e vs CG %.3e "
		"[Theoretical, fine print]\n",
		hhl_quantum_cost(1ULL << 30, 4.0, 100.0, 1e-3),
		cg_classical_cost(1ULL << 30, 4.0, 100.0, 1e-3));
	pr_info("\nNo hardware was contacted: QCX endpoints are TRL 2 "
		"(research doc S12).\n");
	return 0;
}

#endif /* QSCHED_DEMO */
