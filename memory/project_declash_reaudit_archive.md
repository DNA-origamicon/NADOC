---
name: declash-reaudit-archive
description: "History for declash-reaudit — full account of the 2026-08-19 declash auto-trigger retirement (the confounded 6hb_2xT run, the wizard toggle fix). Read on demand only, not routinely."
metadata:
  node_type: memory
  type: project
  status: historical
  originSessionId: 6c67bc07-671e-4f79-b559-639942dbaebe
  modified: 2026-08-20T04:19:18.503Z
---

# Declash auto-trigger retired — full history (2026-08-19)

`md_protocols.py` carried a long-standing "MARKED FOR RE-AUDIT" comment on
`prepare_mgh_slow_release`'s declash auto-enable (any junction inserting 2+ extra bases,
or a design with extensions, auto-forced the gentle 2 fs/rigid/no-HMR ladder tier). The
user ran the real test that comment asked for and the auto-trigger is now **retired**.

## What happened

1. A Declash on/off **toggle** was added to the Job Wizard (checkbox, `CreateJobRequest.declash:
   Optional[bool]`), intending `None` = auto-detect (old behaviour), explicit `True`/`False` =
   override. Shipped with tests, all green.
2. User ran `6hb_2xT` (a design that auto-triggers declash) through the wizard with the
   toggle **left untouched**, believing that meant "off" ("with skip acceleration and no
   declash"). It didn't — untouched still meant auto-detect, so declash silently
   re-engaged.
3. That collided with an EARLIER, unrelated fix: the wizard's Ladder-timestep control
   (`relax_timestep_fs`/`relax_rigid_bonds`/`relax_hmr`) now unconditionally **pins** 4 fs +
   rigid + HMR by default (`pinnedLadderIntegrator` in `md_job_wizard_model.js`), bypassing
   declash's gentle-tier cap on purpose (for the case where the USER deliberately pins it).
   Combined, the untouched run got declash's minimisation-stage clash exclusion **plus** the
   fast/HMR ladder declash's gentle tier exists specifically to keep away from a not-yet-
   declashed structure — exactly the risk `relax_timestep_risk_warning` was written to flag
   (and it did: the warning is recorded verbatim in that job's manifest).
4. Health data: no crash, no RATTLE, clean energetics/temperature/box-volume throughout —
   but C1' pairing degraded through the k0.01 → unrestrained-MGHH stages, and the LAST 40%
   of the final stage was skipped by early-stop while the trend was still declining (early-
   stop can't tell "plateaued well" from "plateaued badly").
5. **User's verdict, both explicit:**
   - WC health is not the metric to judge run quality by (already advisory-only per
     [[feedback_wc_calibration]]; now doubly confirmed — do not raise it as a concern).
   - Early-stop's plateau-blindness is *not* a problem worth fixing — "it seems to be
     working." Do not flag this as a gap in future audits.
   - The actual bug: the wizard must run **exactly what the user specifies** — declash
     must not run when not specified.

## What shipped (2026-08-19, same session)

**`declash` is now explicit-only, default OFF.** `None` (any untouched wizard session, any
pre-toggle caller) resolves to `False`, not auto-detected. Only `True` engages it.

- `prepare_mgh_slow_release` (`md_protocols.py`): `declash = bool(declash)` — the whole
  `design_requires_extra_base_declash`/`design_has_extensions`/`pre_declashed` OR-chain is
  gone from this resolution. Comment marker updated to `RE-AUDIT CONCLUDED` (the literal
  string `"MARKED FOR RE-AUDIT"` no longer appears — canary test updated to match, see
  `test_the_declash_auto_trigger_conclusion_is_recorded`).
- `namd_gbis.build_namd_gbis_package`: same resolution, mirrored.
- `routes_md_plan._relaxation_plan`: `declash = bool(resolved.declash)` — the wizard
  preview agrees with the real build.
- `routes_md.py`'s disk/ETA forecast: `soft = body.force_soft or bool(body.declash)`.
- **The information is not lost, only the silent auto-apply is.** `_relaxation_plan` now
  emits an advisory condition (`id: declash_off_on_a_clash_prone_design`, `kind: warning`,
  `source: CreateJobRequest.declash`) whenever a design would have auto-triggered under the
  old rule but declash is off — fires whether declash ended up off via `None` or an explicit
  `False` (it states an objective fact about the design, not a verdict on the user's choice).
  "Warn, never block" — same rule as [[feedback_namd_4fs_production_only]].
- `pre_declashed` (oxDNA-seeded builds → `rebuild_enm_from_min`) is **unchanged** — unrelated
  mechanism, not surfaced to the wizard.
- Wizard checkbox help text rewritten to say "off by default, always."

Tests: `test_declash_none_is_off_not_auto_detected`, `test_declash_advisory_is_silent_on_an_ordinary_design`
(`tests/test_md_protocol_plan.py`) — both mock `_design_flags` to simulate an
auto-triggering design without needing a real solvated build.

## Open / not done (as of 2026-08-19)

- The two jobs from the confounded run (`1c36b3ca6ee6` relaxation, `00e55345847a`
  production, both archived to `/media/jojo/Archive/NADOC_archive/`) were left as-is —
  not deleted, not re-run. Their manifest's `declash: True` is real and matches what
  actually executed; they are not representative of a clean "no declash" test.
- `design_rmsd_reports` (the other half of the audit's own stated bar — "C1' pairing and
  RMSD-vs-design") is empty on both jobs. `_record_design_rmsd` (`namd_runner.py`) fails
  silently (`logger.debug`, "never fail a run") — preconditions (design.json, DCDs) all
  present, root cause not chased. Worth a follow-up if RMSD-vs-design is wanted for a
  future declash comparison.
- The declash arithmetic bug (`test_declash_stages_run_half_their_intended_length` —
  a declash ladder's step counts stay sized for 4 fs while running at 2 fs, so each rung
  simulates 2.4 ns not 4.8) is UNTOUCHED — still live whenever declash is explicitly
  turned on. Now a rarer path (opt-in only), but not fixed.
