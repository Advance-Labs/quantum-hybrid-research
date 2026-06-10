/* SPDX-License-Identifier: MIT */
/*
 * qsyscall.h - Quantum syscall interface for the hybrid QPU dispatch boundary
 *
 * Stage 4 design artifact for the QuantumLinux paper port.  This header
 * specifies the four-call interface defined by the research doc
 * (docs/research/02-quantum-linux.md, "Proposed Architecture: Hybrid Kernel
 * with QPU Dispatch", syscall table + errno table), reproduced here with the
 * exact names, signatures, and semantics:
 *
 *     QALLOC   - lease qubits (capability fd)
 *     QEXEC    - submit a verified QIR/OpenQASM circuit, run-to-completion
 *     QMEASURE - destructive readout into a classical shadow buffer
 *     QFREE    - RESET leased qubits, return to pool, close capability
 *
 * Architecture invariant (research doc, userspace-flow section): the quantum
 * state NEVER crosses the syscall boundary; only its classical shadow does.
 * Everything userspace keeps - shot buffers, histograms, derived estimates -
 * is classical and flows through the unmodified VFS / mm / net stack.
 *
 * Realism note (research doc, "Syscall additions"): realistically this is
 * one ioctl/io_uring family on a /dev/qpu0 character device - shown as
 * syscalls for clarity.  Both spellings are provided below.
 *
 * NOT an upstream submission.  Per the workflow doc (Risk 4), mainlining a
 * vendor-neutral qpu subsystem is research-doc open problem #1 and is
 * [Speculative]; syscall numbers here are provisional placeholders in the
 * unassigned range above the Linux 6.12 LTS generic table.
 *
 * Standalone compile check (workflow Stage 4, step 6):
 *     gcc -fsyntax-only -std=c11 quantum-linux/kernel-patches/qsyscall.h
 */

#ifndef _QUANTUM_LINUX_QSYSCALL_H
#define _QUANTUM_LINUX_QSYSCALL_H

/*
 * Kernel-type compatibility: in-kernel builds get __u8/__u32/__u64 from
 * <linux/types.h>; standalone/userspace builds map them onto C99 fixed-width
 * types so this header compiles with nothing but a hosted libc.
 */
#ifndef __KERNEL__
#include <stdint.h>
#include <stddef.h>		/* size_t */
#include <sys/types.h>		/* ssize_t */
#include <errno.h>		/* EBUSY, ETIME, ENOEXEC, EIO, ESTALE, EPERM */

typedef uint8_t  __u8;
typedef uint16_t __u16;
typedef uint32_t __u32;
typedef uint64_t __u64;
typedef int32_t  __s32;
typedef int64_t  __s64;
#else
#include <linux/types.h>
#endif /* __KERNEL__ */

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Provisional syscall numbers - design artifact only.
 *
 * Numbered immediately above the last assigned generic syscall in the
 * Linux 6.12 LTS reference tree (the workflow's read-only audit baseline).
 * Real assignment would happen at mainline merge time; see also the ioctl
 * spelling below, which the research doc calls the realistic encoding.
 */
#define __NR_qalloc	463
#define __NR_qexec	464
#define __NR_qmeasure	465
#define __NR_qfree	466

/*
 * Topology hints for qalloc() - struct qalloc_hints.topology.
 *
 * QTOPO_ANY is the only value used by the research doc's userspace flow
 * (".topology = QTOPO_ANY").  The remaining values are design extensions
 * matching the lattice classes of demonstrated 2026 hardware (square-lattice
 * superconducting [Demonstrated: IBM Nighthawk]; all-to-all trapped-ion
 * [Demonstrated: IonQ Forte]); a backend may fail unsupported requests
 * with -EBUSY.
 */
#define QTOPO_ANY	0u	/* no topology constraint (research doc) */
#define QTOPO_LINE	1u	/* extension: 1-D chain of coupled qubits */
#define QTOPO_GRID	2u	/* extension: 2-D square lattice patch */
#define QTOPO_ALL2ALL	3u	/* extension: full coupling (trapped-ion) */

/*
 * Deadline encoding for qexec() - struct qexec_params.deadline.
 *
 * The research doc's flow uses QDEADLINE_RELAXED as an EDF admission hint.
 * Any non-zero value is a relative deadline in microseconds for the
 * qpu_core EDF job queue (admission by coherence deadline).  Coherence
 * deadlines drift with recalibration cycles - scheduling under stochastic
 * deadlines is research-doc open problem #3 [Theoretical]; this ABI only
 * carries the static value (workflow Risk 6: drift handling deferred,
 * -ESTALE stubs the recalibration event).
 */
#define QDEADLINE_RELAXED	0u	/* best-effort EDF admission hint */

/*
 * struct qalloc_hints - placement constraints for a qubit lease
 * @min_t2_us:	minimum acceptable T2 coherence time, microseconds.
 *		Idle quantum state decoheres as F(t) ~= e^(-t/T2)
 *		[Demonstrated]; callers state their budget up front so the
 *		allocator can do calibration-aware placement (research doc:
 *		memory is non-fungible, per-qubit calibration drift makes
 *		placement fidelity-critical [Demonstrated]).
 * @topology:	QTOPO_* connectivity requirement.
 * @__reserved:	must be zero (ABI growth room).
 *
 * Fields per the research doc's userspace flow:
 *     struct qalloc_hints h = { .min_t2_us = 200, .topology = QTOPO_ANY };
 */
struct qalloc_hints {
	__u32 min_t2_us;
	__u32 topology;
	__u32 __reserved[2];
};

/*
 * struct qexec_params - run-to-completion execution parameters
 *
 * Per the research doc's qexec semantics: "p = shots, deadline,
 * feed-forward table", and its userspace flow (shots, deadline,
 * fidelity_floor).
 *
 * @shots:		near-time repetition count (statistically independent
 *			trials - NOT cooperating threads; no shared mutable
 *			state exists between shots within a coherence window).
 * @deadline:		QDEADLINE_RELAXED or relative deadline in us; EDF
 *			admission hint for the qpu_core job queue.
 * @fidelity_floor:	percent; readout completing below this floor fails
 *			the subsequent qmeasure() with -EIO (calibration
 *			drift), per the research doc errno table.
 * @ff_table:		userspace pointer (as u64 for 32/64-bit ABI safety)
 *			to the feed-forward table: the classical
 *			outcome->correction map executed by control FIRMWARE
 *			below the kernel.  Feed-forward must resolve inside
 *			the coherence window; Linux interrupt latency cannot
 *			meet those deadlines reliably [Demonstrated]
 *			(eQASM; QNodeOS real-time QNPU).  0 if unused.
 * @ff_table_len:	bytes at @ff_table; 0 if unused.
 * @__reserved:		must be zero.
 */
struct qexec_params {
	__u64 shots;
	__u32 deadline;
	__u32 fidelity_floor;
	__u64 ff_table;
	__u32 ff_table_len;
	__u32 __reserved;
};

/*
 * Qubit lease descriptor - the kernel-side view of a qset fd capability,
 * readable by the holder via QPU_IOC_LEASE_INFO.
 *
 * The lease is a LINEAR capability (research doc, QISA memory-model design
 * consequence): quantum registers are use-at-most-once resources, never
 * duplicated, explicitly consumed by MEASURE/RESET - closer to Rust move
 * semantics than to pages.  What survives of virtual memory is exactly its
 * naming layer: indirection, isolation, revocation (research doc,
 * Invariant 3; virtual->physical mapping [Demonstrated] by QOS placement).
 */

/* Sized for 2026 hardware: largest shipping module is IBM Nighthawk at
 * 120 qubits [Demonstrated]; the pool an OS must manage is 10^2-10^3
 * physical qubits (research doc, hardware-sizing note). */
#define QLEASE_MAX_QUBITS	128u

/* Lease lifecycle states (struct qlease_desc.state). */
#define QLEASE_STATE_LIVE	1u	/* leased, state may be live */
#define QLEASE_STATE_CONSUMED	2u	/* qmeasure() consumed the state */
#define QLEASE_STATE_STALE	3u	/* recalibration invalidated the
					 * placement; qexec() -> -ESTALE,
					 * caller must re-qalloc */

/*
 * struct qlease_desc - qubit lease descriptor
 * @lease_id:	kernel-unique lease identifier (capability serial).
 * @n_qubits:	number of leased qubits (virtual ids q0 .. q[n_qubits-1]).
 * @cal_epoch:	calibration generation at placement time; a recalibration
 *		cycle bumps the device epoch and stales outstanding leases
 *		(-ESTALE path).
 * @state:	QLEASE_STATE_*.
 * @flags:	QSET_F_* (informational; QSET_F_CLOFORK is always set).
 * @__reserved:	must be zero.
 * @vq_to_pq:	per-process virtual->physical qubit table - "lease assumed:
 *		q0, q1 mapped by the kernel's virtual->physical qubit table"
 *		(research doc, Bell-pair listing).  Entries beyond
 *		@n_qubits are undefined.
 */
struct qlease_desc {
	__u32 lease_id;
	__u32 n_qubits;
	__u32 cal_epoch;
	__u32 state;
	__u32 flags;
	__u32 __reserved;
	__u16 vq_to_pq[QLEASE_MAX_QUBITS];
};

/*
 * qset fd behavior flags (struct qlease_desc.flags).
 *
 * These are NOT requestable options - they document invariants the kernel
 * enforces unconditionally at the syscall boundary (research doc,
 * "Enforced invariants"):
 *
 *   - dup()/dup2()/F_DUPFD on a qset fd  -> -EPERM  (duplication of the
 *     underlying resource is copying: physically undefined [Proven],
 *     no-cloning theorem);
 *   - fork() marks qset fds close-on-fork -> move semantics, at most one
 *     owner (the linear-type discipline, kernel-enforced);
 *   - mmap()/sendfile()/splice()          -> -EPERM  (mapping implies
 *     non-destructive observation: forbidden [Proven], measurement
 *     postulate).
 */
#define QSET_F_CLOFORK	(1u << 0)	/* always set: move-only ownership */
#define QSET_F_NODUP	(1u << 1)	/* always set: dup() -> -EPERM */
#define QSET_F_NOMMAP	(1u << 2)	/* always set: mmap() -> -EPERM */

/*
 * struct qmeasure_result - classical shadow readout buffer layout
 *
 * qmeasure() fills the caller's buffer with this header followed by the
 * packed shadow bits.  Only this classical shadow ever crosses the syscall
 * boundary; the measurement that produced it is destructive and irreversible
 * [Proven] (projective collapse).  qmeasure() is explicitly NOT
 * read(2)-idempotent: it consumes the lease's live state, and a second call
 * on a consumed lease fails.
 *
 * @shots:	shots actually completed.
 * @n_qubits:	qubits read out per shot.
 * @fidelity_est: estimated readout fidelity, percent; values below the
 *		qexec_params.fidelity_floor cause the call to fail with -EIO
 *		instead of returning data.
 * @flags:	QMR_F_*.
 * @payload_len: bytes of @shadow that follow this header
 *		(= (n_qubits * shots + 7) / 8, shot-major bit packing -
 *		matches the research doc's sizing: uint8_t out[2*4096/8]
 *		for 2 qubits x 4096 shots).
 * @shadow:	packed measurement outcomes (flexible array member).
 */
#define QMR_F_PARTIAL	(1u << 0)	/* fewer shots than requested */

struct qmeasure_result {
	__u64 shots;
	__u32 n_qubits;
	__u32 fidelity_est;
	__u32 flags;
	__u32 payload_len;
	__u8  shadow[];
};

/*
 * Error contract - matches the research doc errno table byte-for-byte at
 * the name level.  These cases have no classical precedent:
 *
 *   Errno     Returned by                  Meaning
 *   -EBUSY    qalloc                       Qubit pool exhausted; NO
 *                                          overcommit exists because no
 *                                          swap exists [Proven: swap =
 *                                          tomography over impossible
 *                                          copies, Theta(4^n / eps^2)]
 *   -ETIME    qexec                        Circuit depth exceeds the
 *                                          coherence/QEC budget declared
 *                                          by the device
 *   -ENOEXEC  qexec                        Verifier rejection: gate on an
 *                                          unleased qubit, use-after-measure
 *                                          without RESET, or malformed QIR
 *                                          (static check - the quantum
 *                                          analogue of W^X enforcement;
 *                                          rules in isa-spec verifier_rules)
 *   -EIO      qmeasure                     Readout completed below the
 *                                          fidelity floor in qexec_params
 *                                          (calibration drift)
 *   -ESTALE   qexec                        Lease's placement invalidated by
 *                                          a recalibration cycle; caller
 *                                          must re-qalloc
 *   -EPERM    dup/mmap/sendfile on qset fd Operation is copying or
 *                                          non-destructive observation;
 *                                          physically undefined [Proven]
 *
 * Convenience aliases (negative-errno convention, as the emulator shim
 * returns them):
 */
#define QERR_POOL_EXHAUSTED	(-EBUSY)
#define QERR_COHERENCE_BUDGET	(-ETIME)
#define QERR_VERIFIER_REJECT	(-ENOEXEC)
#define QERR_FIDELITY_FLOOR	(-EIO)
#define QERR_LEASE_STALE	(-ESTALE)
#define QERR_PHYS_UNDEFINED	(-EPERM)

/*
 * ioctl spelling - "realistically: one ioctl/io_uring family on a /dev/qpu0
 * character device" (research doc).  Self-contained command encoding so the
 * header stays standalone-compilable; an in-tree driver would use the
 * _IOW/_IOWR macros from <linux/ioctl.h> with the same magic and numbers.
 */
#define QPU_IOC_MAGIC		'Q'
#define QPU_IOC(nr)		((QPU_IOC_MAGIC << 8) | (nr))

#define QPU_IOC_QALLOC		QPU_IOC(0x01)	/* arg: struct qalloc_hints + n_qubits */
#define QPU_IOC_QEXEC		QPU_IOC(0x02)	/* arg: struct qexec_submit */
#define QPU_IOC_QMEASURE	QPU_IOC(0x03)	/* arg: out buffer (qmeasure_result) */
#define QPU_IOC_QFREE		QPU_IOC(0x04)	/* no arg: RESET + return to pool */
#define QPU_IOC_LEASE_INFO	QPU_IOC(0x05)	/* arg: struct qlease_desc (out) */

/*
 * struct qexec_submit - circuit submission record (ioctl/io_uring spelling
 * of the qexec() argument list; the SQE payload for async submission with
 * completion via io_uring CQE, per the research doc's qexec semantics).
 *
 * @qir_blob:	userspace pointer (as u64) to the QIR/OpenQASM 3 circuit
 *		blob.  Blobs are statically verified BEFORE execution
 *		(-ENOEXEC on rejection); the program - not the quantum
 *		state - is the only thing that crosses this boundary
 *		downward.
 * @len:	blob length in bytes.
 * @params:	execution parameters (see struct qexec_params).
 */
struct qexec_submit {
	__u64 qir_blob;
	__u64 len;
	struct qexec_params params;
};

#ifndef __KERNEL__
/*
 * Userspace wrapper prototypes - signatures reproduced exactly from the
 * research doc's syscall table ("Syscall additions").  In-kernel these are
 * SYSCALL_DEFINEd (or the qpu_core ioctl handler); here they are the libqpu
 * entry points the Stage 4 emulator shim mirrors in Python.
 */

/*
 * qalloc - lease n physical (or logical) qubits
 * @qpu_fd:	fd of the /dev/qpu0 character device.
 * @n_qubits:	number of qubits requested.
 * @h:		topology/fidelity hints (may not be NULL in this ABI rev).
 *
 * Returns a qubit-set fd (capability) on success.  Fails with -EBUSY under
 * pool exhaustion - no overcommit, ever (no swap exists for quantum state).
 */
int qalloc(int qpu_fd, unsigned n_qubits, struct qalloc_hints *h);

/*
 * qexec - submit a verified QIR/OpenQASM circuit for run-to-completion
 *	   execution
 * @qset_fd:	qubit-set capability from qalloc().
 * @qir_blob:	circuit blob (QIR / OpenQASM 3).
 * @len:	blob length in bytes.
 * @p:		shots, deadline, feed-forward table (see struct qexec_params).
 *
 * Run-to-completion: circuits are NEVER preempted - a context switch would
 * require saving quantum state, which is [Proven] forbidden (no-cloning)
 * and [Proven] lossy (measurement).  Async; completion via io_uring CQE.
 * Errors: -ENOEXEC (verifier), -ETIME (coherence budget), -ESTALE
 * (recalibration).
 */
int qexec(int qset_fd, const void *qir_blob, size_t len,
	  struct qexec_params *p);

/*
 * qmeasure - destructive readout of designated qubits into a classical
 *	      shadow buffer
 * @qset_fd:	qubit-set capability.
 * @out:	caller buffer (struct qmeasure_result layout).
 * @out_len:	buffer size in bytes.
 *
 * Consumes the lease's live state; explicitly NOT read(2)-idempotent.
 * Returns bytes written, or -EIO if readout fell below the fidelity floor.
 */
ssize_t qmeasure(int qset_fd, void *out, size_t out_len);

/*
 * qfree - RESET all leased qubits, return them to the pool, close the
 *	   capability
 * @qset_fd:	qubit-set capability.
 *
 * RESET is the active |0> preparation (measure + conditional X) - revocation
 * never copies state, it destroys it, which is always physically allowed.
 */
int qfree(int qset_fd);

#endif /* !__KERNEL__ */

#ifdef __cplusplus
}
#endif

#endif /* _QUANTUM_LINUX_QSYSCALL_H */
