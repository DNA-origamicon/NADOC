# Gold/electrode integration with upstream, 2026-09-15

Integrated local work commit `086a2df8` with `origin/master` at `ecc29558`.
The incoming tree contains graphene pressure-control and display changes, but no
`COMmotion` directive was found in its backend/experiments. The local gold restart
writer retains `COMmotion yes` and its regression assertion.

## Resolution

- Graphene retains upstream pressure-controlled relaxation and NVT production.
  Vacuum-padded two-electrode packages retain fixed-cell NVT, their force callbacks,
  and optional restrained-DNA solvent settling. A solvent-only electrode path now
  tolerates its absent graphene descriptor.
- Box controls retain upstream automatic fit and warning feedback; electrode mode
  owns its compartment dimensions. Surface controls retain upstream setup-preview
  updates and local mutual exclusion with the two-electrode mode.
- Both branches' browser scenarios are retained. Compact restart/calibration
  evidence and scripts are now tracked under `experiments/gold_interfaces/evidence`;
  native trajectories and large run packages remain in the ignored workspace.

## Verification

- `just test-frontend`: **442 files, 6,478 tests passed**.
- Focused backend: **191 passed** across gold, electrode protocol, graphene pressure
  and protocol-plan tests.
- Playwright: **4 passed** (surface sections, two-electrode wizard, box/slab controls,
  small-plate scene stability). Global teardown removed three `__e2e__` documents;
  post-run checks found no remaining test documents or Playwright output directories.
  Background mrDNA listing emitted existing job-save temporary-file errors; the
  selected browser assertions passed. This is not native simulation validation.
- `just test-smart`: `decision: FAST  (fast suite only)`.
  Final run: **8,525 passed, 110 skipped, 27 failed, 9 errors**, 25.44 s pytest time.
  Nine failures concern missing `BigO.nadoc`/`smallO-poly.nass` fixtures; seventeen
  concern the local oxDNA binary lacking the newly required physics signature;
  one failure and nine errors concern aptamer state initialization (`None.nanoparticles`).
  Representative oxDNA and aptamer failures reproduce on an untouched detached
  checkout of upstream `ecc29558` using the same Python environment. No runtime
  capability check was weakened to obtain a pass.

The test selector reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The final broad run flagged one mock lifecycle test at 6.56 s. Inspection confirms
that its fixture runs a small mock executable, not a real simulation. An isolated
guarded rerun passed in 0.57 s (0.16 s test call, 0.01 s setup), with no budget
violation. The slowdown was not reproduced; no budget was raised and no coverage
was moved to the slow suite on that evidence.

`git diff --check` passed; all seven content conflicts were resolved. The initial
post-merge backend run exposed three electrode failures from the missing graphene
descriptor; these passed after the correction and in the final broad run.
