# oxDNA physics audit reproducers

These diagnostics test the installed native executable on CPU and CUDA. They do
not install an engine, change application defaults, launch remote jobs, or post
upstream reports. The September 13, 2026 results use NADOC's pinned
`8028cf33b3cba12992b771156085fa54879f50cd-adaptive-memory-bussi-v2` engine and a
local RTX 2080 SUPER. See `docs/validation/oxdna_fundamental_audit_2026-09-13.md`.

From the repository root, run sequentially:

```bash
.venv/bin/python scripts/validation/oxdna_physics_audit/pair_audit.py
.venv/bin/python scripts/validation/oxdna_physics_audit/nve_pair_audit.py
.venv/bin/python scripts/validation/oxdna_physics_audit/build_bussi_experiment.py
.venv/bin/python scripts/validation/oxdna_physics_audit/thermostat_audit.py
.venv/bin/python scripts/validation/oxdna_physics_audit/harmonic_audit.py
.venv/bin/python scripts/validation/oxdna_physics_audit/summarize.py
```

The native pair test is independent of oxpy. It covers backbone and base contacts,
Lennard-Jones and smoothing branches, rigid rotations, zero-contact controls,
protein–protein controls, and two impulse timesteps. Its mathematical oracle uses
the CPU parameterization, independently differentiated with respect to position
and orientation. A ratio of two is a parameter mismatch, not proof that CPU's
amplitude is the intended published parameter. DNANM CUDA supports only edge
lists; this is not a comparison of edge and non-edge DNANM kernels.

The collision test then checks conservation using both candidate Hamiltonians.
The thermostat tests separate the weak-coupling limit, lack of mixing between
disconnected groups, creation of nonphysical protein angular momenta, and lack of
COM drag. The harmonic test uses four independent simulation seeds, shared
between methods for paired comparisons; saved frames are not independent seeds.
It does not establish statistical equivalence or validate the full strep model.

The Bussi experiment compiles two CPU-only symbol overrides using matching source:
an unchanged control and a version that supplies current kinetic energies to the
published update formula. `LD_PRELOAD` is applied only to chosen child processes.
This requires a matching source/binary ABI and is **not a production fix**. The
installed engine, CUDA thermostat and defaults remain untouched. The audit-only
experiment does not fix every thermostat edge case or prove ensemble correctness.

Output defaults to `workspace/validation/fundamental_audit_20260913`. Set
`NADOC_OXDNA_AUDIT_DIR` to use a different directory,
`NADOC_OXDNA_AUDIT_ENGINE` to select a native executable, and
`NADOC_OXDNA_AUDIT_SOURCE` to select matching source for the CPU experiment.
`nve_pair_audit.py` requires `pair_audit.py`'s fixtures in that directory.
The Python environment needs NumPy and SciPy. The CPU experiment needs g++.
Reports deliberately retain measured errors; a successful process exit is not a
statement that physical checks passed.
