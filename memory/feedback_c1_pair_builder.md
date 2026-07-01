---
name: feedback-c1-pair-builder
description: "C1' pair builder cascade failure when scaffold PSF segment precedes staple segments; sorted-candidates fix"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7344ec2c-6aa8-4c23-9d37-033f12d43944
---

`build_c1_pairs` and `build_wc_pairs` in `backend/core/md_health.py` had a greedy `j > i` ordering constraint that caused systematic mispairings for designs where the scaffold NAMD PSF segment is indexed before staple segments.

**Root cause:** When scaffold atoms (DNAA, indices 0–N) are processed before staple atoms (DNAB+, indices N+), the algorithm encounters inter-helix staple contacts at ~12.58 Å before the correct intra-duplex partners at ~10.4 Å. Once those staple atoms are marked used, subsequent scaffold atoms cannot find their real partners — cascade failure. All 480 pairs ended up at a uniform 12.583 Å (inter-helix crossover-geometry distance), giving 0% paired fraction despite intact structure.

Confirmed diagnosis: the 10hb package has staples before scaffold in the PSF (DNAA=70, DNAB=140, DNAC=210, DNAD=532), so its algorithm works. 3x4SQ has scaffold first (DNAA=668), causing the cascade.

**Fix (applied 2026-06-03):** Collect all cross-segment candidates within [8.5, 13.0] Å, sort globally by distance, then greedily assign shortest-first. Intra-duplex pairs (~9 Å) always win over inter-helix contacts (~12.5 Å) regardless of PSF segment ordering.

Same fix applied to `build_wc_pairs`: non-WC-compatible candidates no longer consume atoms, so each atom gets evaluated against its shortest WC-compatible candidate.

**Why:** Greedy `j > i` constraint makes results depend on PSF atom index ordering, which varies by design.

**How to apply:** Any time a new design shows 0% C1' paired fraction with a sensible mean distance (e.g., 12–13 Å) and the WC check still passes — this is the cascade. Don't chase NAMD parameters; fix the checker.
