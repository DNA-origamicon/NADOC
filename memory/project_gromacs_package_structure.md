---
name: gromacs_package.py structure and key variables
description: Layout of build_gromacs_package, key branch points, and important variables
type: project
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
`backend/core/gromacs_package.py` — `build_gromacs_package()` is the main export function.

**Key variables (computed early, before the tmpdir block):**
- `_nvt_default` — 50000 (solvate) or 25000 (vacuum)
- `_nvt_steps` — user-supplied `nvt_steps` or `_nvt_default`; overridden to 50000 for skip structures in vacuum
- `_has_skips` — True when not use_deformed AND any helix has a LoopSkip with delta <= -1
- `_em_nsteps` — 150000 if _has_skips else 50000

**Key MDP regex patterns** (module-level constants ~line 1889):
- `_STEPS_FROM_MDP` — matches `nsteps = \d+`
- `_DT_FROM_MDP` — matches `^dt = \d+` (MULTILINE)
- `_GENVEL_FROM_MDP` — matches `^gen-vel = \S+` (MULTILINE)

**`_has_skips` block** (vacuum branch, ~line 2380+):
Appended to em.mdp: `constraints = h-bonds`, LINCS settings.
Patched in nvt.mdp and nvt_free.mdp: dt=0.001, gen-vel=no, continuation=yes.

**MDP files generated:** em.mdp, nvt.mdp (restrained), nvt_free.mdp (unrestrained), md.mdp
**README**: inline multi-line string with a dedicated "NON-DEFORMED EXPORT WITH LOOP/SKIP SITES" section explaining all the above.
