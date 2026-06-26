---
name: Overhang lookup table infrastructure
description: Four-stage lookup map pipeline for finding overhang root beads; construction findings and cross-validation design
type: project
originSessionId: 226e0609-1a50-40e9-ace4-af34012ac398
---
## What was built

Four persistent `Map` objects in `main.js` (~line 1059), rebuilt on every `currentDesign`/`currentGeometry` store change:

```
_ovhgSpecMap      id → OverhangSpec
_ovhgDomainMap    id → { strand, domIdx, domain }
_ovhgJunctionMap  id → { junctionBp, junctionDir }
_ovhgRootMap      id → { entry: BackboneEntry, pos: THREE.Vector3 }
```

Two cross-validation maps built alongside but not used in production code:
```
_xval_domainGeo      Map 2 via nuc.domain_index (geometry path)
_xval_junctionDom    Map 3 via domain start_bp/end_bp (no crossovers needed)
```

Debug report via Help → "Show OH Roots" (`_logOvhgMapReport`).

**Why:** `OverhangSpec.pivot` defaults to `[0,0,0]` for all overhangs created by `autodetect_overhangs` and `_reconcile_inline_overhangs` (only `make_overhang_extrude` sets pivot). Gizmo and live preview both need the actual world-space junction bead position.

---

## Findings during construction (thought vs. reality)

### Bug 1: Wrong domain-index lookup (now fixed)
**Thought:** `strand.domains.findIndex(d => d.helix_id === spec.helix_id)` finds the right domain.
**Reality:** If a strand visits the same helix twice (possible for multi-domain staples), `findIndex` returns the FIRST match, which may not be the overhang domain.
**Fix:** Use `d.overhang_id === spec.id` — this is always set by all three OverhangSpec creation paths.

### Bug 2: Cross-validation domain path uses authoritative index
**Thought:** Both design and geometry paths would use helix_id matching.
**Reality:** The geometry path uses `nuc.domain_index` (emitted by the backend from the actual domain loop index). This is immune to the double-helix-visit problem and serves as an independent check.

### Finding: design.crossovers completeness
**Thought:** `autodetect_overhangs` creates no crossover, so inline overhangs might lack one.
**Reality:** Crossovers for all inter-helix strand transitions are in `design.crossovers` from the original cadnano/scadnano import. `autodetect_overhangs` only tags domains; the crossover was already there. If crossovers are absent it means they were never imported.

### Finding: index and direction types
- `HalfCrossover.index` and `nuc.bp_index` are both **global** bp indices — they match directly.
- `xo.half_*.strand` and `nuc.direction` are both `'FORWARD'`/`'REVERSE'` strings — match directly.

### Finding: junction bp derivation (domain-endpoint path)
In NADOC `start_bp` is ALWAYS the 5′ end regardless of direction:
- FORWARD: `start_bp < end_bp` (5′ at lower index)
- REVERSE: `start_bp > end_bp` (5′ at higher index)

So the junction bp is **direction-independent**:
```
overhang at 3' end of strand (domIdx > 0) → junction = start_bp  (5' end of domain)
overhang at 5' end of strand (domIdx = 0) → junction = end_bp    (3' end of domain)
```
No direction check needed. Applies equally to HC and SQ lattice types.

**Bug fixed (2026-04-25):** Original cross-validation formula included a wrong direction check that swapped the result for REVERSE domains. Corrected to `isFirst ? domain.end_bp : domain.start_bp`.

### Finding: O(1) backbone lookup
`helixCtrl.lookupEntry("helix_id:bp_index:direction")` (exposed by `design_renderer.getHelixCtrl()`) gives O(1) access to backbone entries. Replaces `backboneEntries.find(...)` linear scan.

---

## Cross-validation design

Map 2 (domain): design path (`d.overhang_id`) vs geometry path (`nuc.domain_index`)
Map 3 (junction): domain-endpoint path (primary) vs crossover path (`_xval_junctionXover`)

**Primary/cross-val swap (2026-04-25):** Domain-endpoint is primary; crossover path is cross-validation. Reason: `design.crossovers.find()` returns the FIRST crossover matching a helix pair — wrong when multiple strands share the same parent↔overhang helix pair (e.g., 80/90 mismatches seen on a real HC design). Domain-endpoint path is unambiguous because it operates per-domain, not per-helix-pair.

**How to apply:** If `_logOvhgMapReport()` shows many `junction xval mismatches` with `xover=` values repeated across multiple overhangs, the crossover path is colliding on a shared helix pair. The domain-endpoint primary is already correct; the xval report entries are expected for such designs.
