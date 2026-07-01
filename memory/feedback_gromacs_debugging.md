---
name: GROMACS debugging approach for LINCS failures
description: Diagnostic steps that worked for tracking down LINCS failures; what to check and in what order
type: feedback
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
When NVT fails with LINCS warnings and catastrophic displacements, inspect em.gro BEFORE assuming it is a velocity or timestep issue.

**Why:** The first instinct (reduce dt, set gen-vel=no) was applied but failed because the root cause was bad starting geometry from EM — C2-H2 bonds at 2.5 Å in em.gro. Fixing dt/gen-vel had no effect when LINCS needed to correct a 1.4 Å bond length error at step 0.

**Diagnostic order:**
1. Check em.gro for bad bond lengths: `grep -A1 "C2 " em.gro | head -40` and compare to conf.gro. C2-H2 should be ~1.08 Å; if it is ~2.5 Å, EM diverged to a false minimum.
2. Check EM convergence: "converged" with Fmax < emtol does NOT mean geometry is correct — a 2.5 Å C2-H2 bond has force ~426 kJ/mol/nm, below emtol=1000.
3. Only after confirming em.gro geometry is clean, investigate NVT parameter issues (dt, gen-vel, continuation).

**How to apply:** Any future LINCS failure investigation should start with a bond-length audit of the EM output GRO before touching mdp parameters.
