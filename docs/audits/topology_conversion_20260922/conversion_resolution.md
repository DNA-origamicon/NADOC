# C1–C7 conversion fixes and export review

Implemented 2026-09-22 with user authorization. No native simulations, phase
constant changes, or mrDNA changes. R-group protections remain in place.

| Finding | Resolution |
|---|---|
| C1 — periodic round-trip corruption | Both exporters reject designs carrying periodic-seam intent rather than erase that intent. The same-helix caDNAno parser defect is fixed separately. No sidecar or implicit periodic reconstruction is introduced. |
| C2 — invalid pointers / invented positions | caDNAno input checks pointer shape, range, reciprocity, helix-number uniqueness, and modification consistency before tracing. Tracing splits discontinuous same-helix paths instead of filling their gaps; directed forced-ligation records retain the transitions. Singleton domains use strand/helix parity. A uniform parity-origin correction preserves ordinary imported designs on re-export. |
| C3 — dropped scadnano loopouts | Internal loopouts become junction `extra_bases` on the exact 3′→5′ transition, including same-helix loopouts. Their sequence is separated from domain sequence; unknown bases become N. Invalid terminal/consecutive loopouts are rejected. Voltron import/domain-end coverage remains intact. |
| C4 — dropped junction extras | Both current exporters block junction extra bases with a concrete report. scadnano itself has loopout support, but this exporter does not yet encode NADOC junction extras as loopouts. Terminal chemical modifications also block export; caDNAno terminal extension bases block export. scadnano terminal extensions preserve sequence, filling unassigned domain sequence with N when necessary and reporting that substitution. |
| C5 — overwritten modification declarations | Conflicting insertion/deletion declarations are rejected. Missing declarations on another overlapping domain are treated as zero, so asymmetric source modifications are rejected rather than silently symmetrized into NADOC's helix-level model. Symmetric modifications remain supported. |
| C6 — deleted circular molecules | caDNAno circular scaffolds are retained as linear scaffolds at a deterministic sequence origin, with a warning. scadnano retains its established scaffold linearization. Circular non-scaffold molecules reject the entire import in both formats; they are never silently dropped. |
| C7 — permissive schema / premature installation | Unknown grids, duplicate indices, invalid/empty domain bounds, missing helix references, unsupported source transforms/groups and chemical modifications fail before installation. Source topology is checked again after import processing and before replacing the document. Failed imports preserve the active document/history. |

## Export dialog and backend contract

Both the 3D view and Origami Editor use the same dialog. Before downloading caDNAno
or scadnano, it lists each present unsupported feature category with a count and
its consequence. Examples include:

- Junction extra bases, periodic seams, unrealized connections, invalid topology,
  terminal chemical modifications, noncanonical caDNAno direction parity, isolated
  one-position caDNAno strands, and unresolved/synthetic strand material.
- Assigned sequences (caDNAno), terminal extensions and their labels, scaffold
  colors, strand names/notes, overhang/binder domain identities, junction annotations.
- Cluster membership/transforms, nucleotide transforms, deformations, native residue
  coordinates, absolute helix placement/phase, and relabeled negative coordinates.
- Protein/nanoparticle content, saved scientific setup and design provenance,
  overhang connection metadata, duplex annotations,
  simulation/animation settings, plate layouts, views, annotations, and feature history
  when present. Nondefault NADOC-only design fields are inventoried generically so
  newly added fields cannot silently escape the report.
- Photoproduct chemistry: caDNAno blocks it; scadnano reports that the existing
  CPD-fork extension is not portable to standard scadnano.

Cancel/Escape closes without downloading. A report with molecular blockers offers
only Close. A warning-only report requires **Export with listed losses**. The
backend checks a digest of the exact design and target format, so a stale dialog
cannot authorize losses in an edited design. Direct API downloads cannot bypass
this review; unsupported molecular content cannot be acknowledged away. The
export operation does not mutate the original design.

`GET /api/design/export/compatibility/{cadnano|scadnano}` returns the report and
review token. Pass that token as `compatibility_token` to the corresponding export
endpoint. A stale/missing review returns 409; blocked conversion returns 422.
Core exporters also enforce molecular blockers.

The explicit chemical-modification JSON keys were checked against the
[official scadnano format documentation](https://github.com/UC-Davis-molecular-computing/scadnano/blob/main/README.md).
These are current NADOC converter capabilities, not claims that the external
formats can never support the rejected feature.

## Evidence

- [Warning dialog](export-warning.png), [blocked export](export-blocked.png), and
  [browser results](conversion_browser.json). Tested cancel, confirmed download,
  blocked extra-base export, and the Origami Editor dialog through real servers.
  Representative `.nadoc` topology was loaded and visually inspected. Temporary
  workspace, browser downloads, processes and credential file are cleaned up even
  on failure.
- [Repeated audit probes](results_conversion_fixed.json). Original audit evidence
  is unchanged; expected strict rejections appear as exceptions in this observation
  harness rather than as failed regression tests.
- Focused conversion/API tests: 130 passed before the additional loopout cases;
  loopout/import/domain-end follow-up: 90 passed. Frontend suite: 6,757 passed;
  final dialog/menu tests: 22 passed.

Final verification:

- `just test-smart`: **FAST (fast suite only)**; **8,854 passed, 7 skipped,
  7 failed** in 145.03 seconds (154 seconds under the guard). All seven failures
  are the existing photoproduct-review fixture failures on
  `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`.
  This is not an all-green full-suite result.
- Final caDNAno/scadnano regression run: **89 passed**. Final inventory/API
  follow-up: **27 passed**. Separate timing/headless follow-up: **30 passed**.
- `just smoke`: **23 passed**, including app boot/render and assembly/session
  teardown. Both frontend unit suites and the real export dialog exercise passed.
- `just lint`: passed. `just lint-memory`: zero errors, 59 existing size warnings.
- Slow-test triage: the concurrent backend/browser runs produced three per-test
  outliers (5.78, 5.33, 5.19 seconds). Source inspection found a deterministic
  coating calculation, an assembly snapshot-cap test, and a mocked runner test;
  no production engine was launched. A guarded isolated rerun measured **3.89,
  1.60, 1.27 seconds**, respectively, and completed in 13 seconds with zero
  violations. No test classifications or budget settings were changed. The
  broader run's aggregate runtime remains over budget.
- Temporary browser workspaces/processes/credentials and smoke `__e2e__` parts,
  assemblies and proven test revision stores were cleaned up; the configured
  Playwright output directory is empty. No revision store changed since the
  smoke run began remains; older cached test stores were left untouched.

Deferred output, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The full guarded run preceded the last inventory-label/provenance additions and
explicit parser strand-kind parameter cleanup; those were covered by the final
focused runs and repeated browser exercise.

`frontend/src/main.js` LOC delta: **0**. Origami Editor composition root delta:
**+3 lines**, consisting of shared-controller import/initialization and thin wiring.
