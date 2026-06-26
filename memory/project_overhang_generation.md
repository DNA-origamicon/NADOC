---
name: Overhang sequence generation — merged to master
description: Johnson et al. 5-mer algorithm for rare overhang sequences; spreadsheet UI; merged 2026-04-15
type: project
originSessionId: 7f83f977-ca7f-43c6-b309-5f4c6a90c842
---
Merged to `master` on 2026-04-15 (commit 80a64f8).

## What was built

**Algorithm** — `backend/core/overhang_generator.py`
- `generate_overhang_sequences(scaffold_seq, staple_seqs, length, count, gc_min, gc_max, staple_weight)`
- Johnson et al. DOI: 10.1021/acs.nanolett.9b02786
- 7 steps: 5-mer score map → seed selection (≤1st pct, relax to 50th for ≥10 seeds) → greedy extension → GC filter (35–75%) → hairpin/dimer filter → corpus-score filter (≤45th pct) → diversity via growing corpus
- Fallback to random if algorithm can't fill quota within 50 outer iterations

**Backend** — `backend/api/crud.py`
- `POST /design/overhang/{id}/generate-random` — generates or **overwrites** (no longer 422 on existing sequence)
- `POST /design/generate-overhang-sequences` — generates all undefined overhangs one-at-a-time, growing diversity corpus per overhang
- `_random_dna` removed; replaced with calls to `generate_overhang_sequences`
- `_ovhg_domain_lengths` uses `abs()` for REVERSE-direction domains
- `patch_overhang` uses `model_fields_set` (Pydantic v2) to detect explicit null
- Clearing overhang sequence calls `_resplice_overhang_in_strand` to restore N×len in strand.sequence

**Spreadsheet** — `frontend/src/ui/spreadsheet.js`
- Gen button persists on sequenced overhangs (click to regenerate)
- Right-click context menu on ovhg_5p, sequence, ovhg_3p columns → "Clear sequence"
- Context menu flips above cursor near bottom viewport edge
- Unsequenced overhang cells: N×len label + click-to-edit input
- Sequence column strips terminal overhang bases from display (dsDNA portion only)
- Toast on Gen cites algorithm DOI

**Why:** User wanted rare overhang sequences that avoid off-target binding and secondary structure.
**How to apply:** When touching overhang sequence generation, see `backend/core/overhang_generator.py`.
