# Overhang generation: final-oligo screening

The overhang **Gen** button uses the existing Johnson rare-k-mer search, then
screens each candidate in its design context before saving any sequences:

- the assembled overhang, including locked sub-domains;
- the complete staple carrying it, including its other overhangs;
- every affected binder and complete connected linker, including the other arm
  and the bridge (reverse-complemented for the second dsDNA linker strand).

Hairpins and self-dimers use the same primer3 calculations as the interactive
checker: 0 mM Na+, 10 mM Mg2+, 200 nM oligo. Overhangs and linkers must have
both Tm values at or below **30 °C**. Intended overhang–linker duplexes are not
rejected as unwanted heterodimers.

Whole staples are checked against separate hairpin and self-dimer limits of
`max(30 °C, fixed-body Tm)`, masking the variable overhang when calculating that
baseline. This permits structures already present in bases Gen cannot change,
but does not permit an increase in the maximum Tm for either structure type.
It does not establish that every individual structure below that maximum is
unchanged. Staple body sequences and locked overrides are preserved.

Accepted staple and linker sequences are updated together in one undoable
operation. Single-overhang, bulk, and sub-domain generation share the screen.
Bulk generation evaluates each candidate against preceding accepted changes,
and commits only after the entire batch succeeds.

If Johnson candidates fail, bounded random exploration uses the same structural
constraints. Exhaustion returns an explanatory error and leaves the design
unchanged. The standalone random-sequence endpoint retains its existing behavior.
The direct-pair UI does not update the partner after a failed generation.

## Limits and validation

The other linker arm or bridge can contain a structure above the cutoff on its
own. Regenerating just one overhang cannot guarantee a solution in that case.
An exhausted search is not proof that no possible sequence exists. Undefined
bases and long sequences retain the interactive checker's partial-sequence and
60-nt-window limitations.

On an unchanged copy of `VoltronCoreArmV2`, one-arm trials cleared four of six
flagged linkers. Two remained constrained by the unchanged arm at the strict
30 °C cutoff. A browser test clicked the real Gen button for
`ovhg_h_XY_16_26_184_3p`: the connected linker's 85.8 °C warning cleared, and the
stored linker matched the automatically rechecked sequence. The test used the
current design topology and sequences with history/loadouts removed for loading
speed, in a disposable workspace. The saved source file's SHA256 was unchanged.

Regression coverage in `tests/test_hairpin_dimer.py` checks structures formed
only in the full staple/linker, exact committed bridge/complement sequences,
fixed-body baselines, locked bases, screened fallback, and atomic failures.
`frontend/src/ui/overhang_gen.test.js` also checks the failed-pair guard.

Validation on 2026-09-21:

- Focused backend tests: 69 passed; changed Python files pass Ruff.
- Full frontend suite: 458 files / 6,590 tests passed.
- `just test-smart`: **FAST**, 8,652 passed, 116 skipped, 30 failed,
  9 setup errors; 52.63 s pytest / 57 s guarded wall time, no budget violations.
  Failures are in animation, simulation/assembly, scadnano and aptamer tests,
  outside the changed generation tests. This is not a green repository-wide run.
- Required `triage-slow-tests` work isolated a test's real workspace scan and
  registered genuine CPD minimization / NAMD artifact integrations in the slow
  suite, with matching source selectors. No test budget was raised.
- `main.js` LOC delta: 0.

The selector's deferred-suite message:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Detailed run logs and the isolated browser-check script are retained in
`.development-artifacts/overhang-sequence-screen/`. No temporary browser
workspace or `__e2e__overhang-screen` design remains in the user workspace.
