"""qos -- the QLOS v0.1 runtime package (QuantumLinux OS runtime).

Package facade over the two QLOS runtime modules (design doc
quantum-linux/qos/QLOS-DESIGN-v0.1.md, section 8 -- BINDING contract):

* ``qsyscalls`` -- :class:`QLOSRuntime`, the user-space shim mirroring the
  four-call ``qalloc``/``qexec``/``qmeasure``/``qfree`` ABI of
  ``kernel-patches/qsyscall.h`` semantically (section 8.3).
* ``scheduler`` -- :class:`QProcess` / :class:`LeaseManager` /
  :class:`QPUScheduler`, the process model, linear-capability lease
  accounting, and deadline-aware FIFO admission control (section 8.4).

Naming (design doc section 1): this runtime is QLOS, never "QOS" -- "QOS"
always means the quantum operating system of Giortamis et al. (OSDI '25)
that the research doc cites; the package directory ``qos/`` is a path, not
the project name.

Everything exported here is a CLASSICAL control plane around the
``emulator/qcpu.py`` statevector backend: no quantum state ever crosses
these interfaces, only its classical shadow (research doc
docs/research/02-quantum-linux.md, userspace-flow section; no-cloning and
measurement postulate, both [Proven]).

Import mechanics: the runtime modules are plain top-level modules behind
``sys.path`` seams (design doc section 8), so ``import qsyscalls`` and
``import qos; qos.QLOSRuntime`` resolve to the SAME module objects --
``qsyscalls``/``scheduler`` register once in ``sys.modules`` either way.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# Path seam (design doc section 8): make the sibling modules importable as
# plain modules no matter how this package itself was reached.
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from qsyscalls import (  # noqa: E402
    # qsyscall.h constants (names identical to the header).
    QTOPO_ANY, QTOPO_LINE, QTOPO_GRID, QTOPO_ALL2ALL,
    QDEADLINE_RELAXED, QMR_F_PARTIAL,
    QLEASE_STATE_LIVE, QLEASE_STATE_CONSUMED, QLEASE_STATE_STALE,
    QLEASE_MAX_QUBITS,
    QSET_F_CLOFORK, QSET_F_NODUP, QSET_F_NOMMAP,
    # Errno-style exceptions (qsyscall.h QERR_* contract).
    QLOSError, PoolExhaustedError, CoherenceBudgetError,
    VerifierRejectError, FidelityFloorError, LeaseStaleError,
    PhysUndefinedError, BadDescriptorError,
    # Result structs + the runtime.
    LeaseInfo, MeasureResult, QLOSRuntime,
)
from scheduler import (  # noqa: E402
    CYCLES_PER_US, COST_1Q, COST_2Q, COST_MEASURE, COST_RESET,
    QProcState, QProcess, Lease, LeaseManager, QPUScheduler,
    QObjLike, estimate_cycles,
)

__version__ = "0.1.0"

__all__ = [
    # constants (qsyscall.h mirror)
    "QTOPO_ANY", "QTOPO_LINE", "QTOPO_GRID", "QTOPO_ALL2ALL",
    "QDEADLINE_RELAXED", "QMR_F_PARTIAL",
    "QLEASE_STATE_LIVE", "QLEASE_STATE_CONSUMED", "QLEASE_STATE_STALE",
    "QLEASE_MAX_QUBITS",
    "QSET_F_CLOFORK", "QSET_F_NODUP", "QSET_F_NOMMAP",
    # scheduling policy constants (design doc section 5)
    "CYCLES_PER_US", "COST_1Q", "COST_2Q", "COST_MEASURE", "COST_RESET",
    # errno-style exceptions
    "QLOSError", "PoolExhaustedError", "CoherenceBudgetError",
    "VerifierRejectError", "FidelityFloorError", "LeaseStaleError",
    "PhysUndefinedError", "BadDescriptorError",
    # syscall layer
    "QLOSRuntime", "LeaseInfo", "MeasureResult",
    # process model / scheduler layer
    "QProcState", "QProcess", "Lease", "LeaseManager", "QPUScheduler",
    "QObjLike", "estimate_cycles",
    "__version__",
]
