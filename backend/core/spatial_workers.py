"""Thread policy for spatial queries used by trajectory analysis."""

import os


def spatial_workers():
    # cKDTree's explicit worker count is independent of OMP/BLAS limits.
    # Background precomputation has one CPU and a bounded address space;
    # workers=1 executes inline without allocating additional thread stacks.
    return 1 if os.environ.get("NADOC_PRECOMPUTE_WORKER") else -1
