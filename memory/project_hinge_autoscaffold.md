---
name: project_hinge_autoscaffold
description: "Hinge scaffold routing — route ONE seamed strand through forced-ligation gap-bridges (hinge primitives), self-gated against the scaffold-routing invariants. + the regression gate that now guards ALL autoscaffold paths."
metadata: 
  node_type: memory
  type: project
  originSessionId: 7cfe31c9-8568-42d1-a022-298315c1bd8f
---

# Hinge autoscaffold + scaffold-routing regression gate (2026-06-26)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Hinge primitives (`2x2_single` / `2x4_double` / `2x6_triple_hinge_link` in
`workspace/Primitives/`) are two rigid leaves bridged across a gap by **forced
ligations** (cross-gap scaffold links). Autoscaffold must route ONE strand through
the bridges. A forced ligation here is a *structural bridge to route through*, NOT a
one-off manual anchor to route around.

## The regression gate (the durable, critical deliverable)
`backend/core/scaffold_invariants.py` — `scaffold_routing_invariants(design, *,
require_seams) -> list[str]` (empty == compliant). Two invariants every autoscaffold
output must satisfy:
1. **Seams present** (`require_seams=True` for seamed/matched/section; False for
   seamless): `scaffold_seam_positions(design)` non-empty (real mid-helix double
   crossovers, not a seamless raster).
2. **≥3-base ssDNA margin**: every *non-seam* scaffold crossover (end/turn cap) sits
   ≥`MIN_SSDNA_MARGIN`(=3) bp clear of any staple domain on its helix (the hard-won
   "scaffold crossovers live in extended ssDNA, never buried in a staple"). Seam
   crossovers are exempt (intentionally mid-duplex). Vacuous on helices w/o staples.
Why it exists: `validate_design` encodes NONE of this; the first hinge attempt shipped
a seamless raster (no seams, crossovers buried in staples) tests-green. See [[LESSONS]] H8.

Tests `tests/test_scaffold_invariants.py`: checker unit tests + a **property test
parametrized over EVERY autoscaffold entry point** (`ROUTING_ENTRY_POINTS` =
seamed/matched/seamless) asserting compliance, a stapled-margin test, and a
regression pin on the known-bad output. **MERGE RULE: a new autoscaffold return path
must be added to `ROUTING_ENTRY_POINTS`.**

<a id="the-hinge-router-compliant-retry"></a>
- [The hinge router (compliant retry)](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#the-hinge-router-compliant-retry)

<a id="status-honest"></a>
- [Status (honest)](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#status-honest)

<a id="caution-workspacehinge_route_testnadoc-was-overwritten"></a>
- [CAUTION: `workspace/Hinge_route_test.nadoc` was OVERWRITTEN](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#caution-workspacehinge_route_testnadoc-was-overwritten)

<a id="why-earlier-approaches-failed-dont-retry"></a>
- [Why earlier approaches failed (don't retry)](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#why-earlier-approaches-failed-dont-retry)

<a id="automation-ledger-design-automation-loop-intake-2026-06-26"></a>
- [Automation ledger (design-automation loop, intake 2026-06-26)](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#automation-ledger-design-automation-loop-intake-2026-06-26)

<a id="decoded-gold-weave-2x6-hinge_route_test-restored-2026-06-26--the-routing-target"></a>
- [DECODED gold weave (2x6 Hinge_route_test, restored 2026-06-26) — the routing target](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#decoded-gold-weave-2x6-hinge_route_test-restored-2026-06-26--the-routing-target)

<a id="generalization-investigation-2026-06-26-arbitrary-2x2n--methods-tried--the-reframed-correct-model"></a>
- [GENERALIZATION INVESTIGATION (2026-06-26, arbitrary 2x(2n)) — methods tried + the REFRAMED correct model](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#generalization-investigation-2026-06-26-arbitrary-2x2n--methods-tried--the-reframed-correct-model)

<a id="new-reference-set--ladder-core-prototype-2026-06-26"></a>
- [NEW REFERENCE SET + LADDER-CORE PROTOTYPE (2026-06-26)](details/project_hinge_autoscaffold/01-the-hinge-router-compliant-retry.md#new-reference-set--ladder-core-prototype-2026-06-26)

<a id="bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-goal"></a>
- [bp REALIZER — SHIPPED & WIRED 2026-06-26 (2x routes live; the user's goal)](details/project_hinge_autoscaffold/02-bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-g.md#bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-goal)

<a id="status-k2-all-work-2x22x42x6--3x23x4--2026-06-27"></a>
- [STATUS: k≥2 ALL WORK (2x2/2x4/2x6 + 3x2/3x4) — 2026-06-27](details/project_hinge_autoscaffold/02-bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-g.md#status-k2-all-work-2x22x42x6--3x23x4--2026-06-27)

<a id="full-pipeline-automated-2026-06-27--build-kxn--route--verify"></a>
- [FULL PIPELINE AUTOMATED 2026-06-27 — build kxN → route → verify](details/project_hinge_autoscaffold/02-bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-g.md#full-pipeline-automated-2026-06-27--build-kxn--route--verify)

<a id="seamless-hinge-routing--shipped--wired-2026-06-27-k2-all-work-buried-nick"></a>
- [SEAMLESS hinge routing — SHIPPED & WIRED 2026-06-27 (k≥2 all work, BURIED NICK)](details/project_hinge_autoscaffold/02-bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-g.md#seamless-hinge-routing--shipped--wired-2026-06-27-k2-all-work-buried-nick)

<a id="stapleoverhang-fls-no-longer-derail-routing-2026-06-27--bound-end-to-root"></a>
- [STAPLE/OVERHANG FLs NO LONGER DERAIL ROUTING (2026-06-27) — `bound end to root`](details/project_hinge_autoscaffold/02-bp-realizer--shipped--wired-2026-06-26-2x-routes-live-the-users-g.md#stapleoverhang-fls-no-longer-derail-routing-2026-06-27--bound-end-to-root)

## ⚠️ WORKSPACE FIXTURE CORRUPTION (2026-06-27) — `2x6_triple_hinge_link.nadoc`
The 2x6 PRIMITIVE file (`workspace/Primitives/`) got OVERWRITTEN with a ROUTED design
(1 scaffold strand + 17 crossovers, vs the original 18 seed strands + 0 crossovers) —
mtime today, NOT by any session script (they only read it; likely the user's running
app saved over it). These workspace `.nadoc` files are NOT git-tracked, so no restore.
The realizer correctly DECLINES a routed input → `test_realizes_single_gate_clean_
strand[2x6]` + `test_multi_link_hinge_routes[triple]` now SKIP (guarded:
`design.crossovers or ≤1 scaffold strand` ⇒ not a primitive). Self-contained build→
route coverage (`test_build_kxn_*`) is unaffected. To restore a valid 2x6 primitive:
`build_hinge(2, 6)` (the generator) → save to the path — ASK the user first (don't
overwrite their .nadoc unprompted).
