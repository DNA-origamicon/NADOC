# Mobile streptavidin validation — 2026-09-16

The local RTX 2080 SUPER passed native CUDA force/torque checks for off-surface
pocket grafts, DNA–coating contacts, and contact between two composite particles.
Pocket/contact checks cover float and mixed precision. The existing thiol
force, exclusion and restart regression also passed on the updated engine.

Generated 16-base biotinylated handles ran for 30,000 CUDA steps in both coating
placement modes. Final pocket-to-backbone distances were 2.116 nm (adsorption)
and 2.275 nm (biotin tether), versus a 2 nm effective rest length. Core translations
were 0.0938 and 0.0958 nm. Finite trajectories and reciprocal mechanics establish
numerical operation, not equilibrium linker statistics or binding free energies.

The 6,012-nucleotide, 20,000-step timing comparison measured:

| System | Runtime | Steps/s |
| --- | ---: | ---: |
| DNA only | 7.837 s | 2,552 |
| One mobile gold core plus seven rigid tetramers | 11.255 s | 1,777 |

The latter is 43.6% more wall time. This single timing pilot retains a thiol graft
to exercise the coating overhead; the separate generated-handle runs exercise
biotin attachment. It is not a controlled benchmark across hardware or large
coating counts, and does not qualify origami pairing retention.

Focused backend checks: 53 passed across mobile gold/strep, coating guards,
staleness and RunPod staging. Following the new mobile-default API change,
17 further focused tests passed (7 slow tests deselected), including mobile job
creation and preservation of legacy fixed-core jobs.

`just test-smart` selected **FAST**. Its full fast-suite attempt was not clean:
8,609 passed, 30 failed, 43 skipped and 9 errors. Failures included headless field,
NAMD/PEG, photoproduct and aptamer tests; the coated topology guard failure was
fixed and its focused regression passed. This is not a claim that the full
repository suite passes. The selector reported:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

`just test-frontend` passed: 445 test files, 6,505 tests.

No RunPod jobs were attempted; spend remains $0 against the $5 cumulative cap.
Live browser playback was not exercised and is recorded in manual validation debt.

Compact measurements are in [the JSON evidence](oxdna_mobile_strep_2026-09-16.json).
Raw final evidence is under `experiments/mobile_gold/ws/strep_*20260916`; the
superseded first validation run was deleted. No development design or job from
this campaign was placed in the main user workspace.

Reproduce with fresh isolated output paths:

```bash
.venv/bin/python -m experiments.mobile_gold.strep_validation --output experiments/mobile_gold/ws/strep_new --binary "$HOME/.local/share/nadoc/engines/oxdna-mobile-gold/current/bin/oxDNA"
.venv/bin/python -m experiments.mobile_gold.benchmark --output experiments/mobile_gold/ws/strep_timing_new --coating-count 7
```

See [model assumptions](../oxdna_mobile_strep.md). The full chain is persistent
and nonreactive; compliance, coating mass/drag and origami equilibration remain
unqualified.
