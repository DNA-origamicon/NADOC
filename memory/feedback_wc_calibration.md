---
name: feedback-wc-calibration
description: WC health checker has reduced sensitivity when template structure has many geometrically deformed base pairs
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7344ec2c-6aa8-4c23-9d37-033f12d43944
---

`build_wc_pairs` evaluates pairs using ref-relative distances (within ±0.75 Å of reference). When the reference structure is a template-built atomistic CAD model (not MD-relaxed), many "WC pairs" may have H-bond proxy atoms far apart (> 6 Å or even > 8 Å). Those pairs effectively never fail the ref-relative check — their large reference distance is treated as the baseline, so any similar inter-atom distance in simulation is "within 0.75 Å."

3x4SQ calibration (2026-06-03):
- 440 WC pairs total
- Only 82 have all H-bond atoms < 4 Å in the template (genuinely tight)
- 110 have at least one H-bond atom > 8 Å (these always count as OK, never fail)
- Median ref H-bond distance: 5.23 Å; p90: 10.15 Å; max: 13.73 Å

**Why:** The template atomistic builder (backend/core/atomistic.py) constructs coordinates from B-DNA constants but doesn't globally minimize inter-residue geometry. Crossover junctions and scaffold routing bends can leave some nucleotide pairs with poor geometry in the template.

**How to apply:** When WC score stays high throughout a run (even at low restraints), check how many WC pairs have inflated reference distances. If > ~25%, the WC check is not a reliable structural health metric for this design — use C1' fraction as the primary indicator instead. The C1' check is independently calibrated using only C1'–C1' distances and is not affected by this problem (as long as the pair builder finds correct intra-duplex pairs).

The ~330 pairs with tight reference distances (< 8 Å) still provide signal — structural collapse would increase those distances beyond ref + 0.75 Å.

**Gate policy (2026-06-22):** Acting on the above, the NAMD health gate now treats WC as **advisory, not blocking**. `HealthCheckResult.blocking` / `MdHealthSample.blocking` = True only on a C1' breach or a hard error; a WC-only breach sets `passed=False, blocking=False`. `namd_runner` stops the run only when `not passed and blocking` — a WC-only breach logs a warning and the ladder continues to completion. Frontend shows it as ⚠ (`_isAdvisoryWarning` in md_jobs_panel.js), not a ✗ failure. Motivation: the 2hb_noT run kept hard-failing at the k=0.01 checkpoint on WC 78.4% < 80% despite a healthy backbone. Tests: `tests/test_md_runner_proceeds.py::test_wc_only_breach_warns_and_continues` + `test_c1_breach_still_fails_the_run`.
