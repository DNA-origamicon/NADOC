---
name: overhang-sequence-display
description: Overhang sequences shown everywhere + made simulation-real. Sidebar + 3D overlay now read the ASSEMBLED overhang sequence (sub-domain overrides → parent → N); cadnano editor now shows base letters (overlay un-hidden); connect/apply/set auto-assigns so linker-complement / binder strands carry real RC bases. Shipped 2026-06-29.
metadata: 
  node_type: memory
  type: project
  originSessionId: 77880eb1-e9cc-402f-9567-1e823c0634a5
---

# Overhang sequences: shown everywhere + simulation-real (2026-06-29)

> **Update 2026-06-30:** the end-to-root **binder splice** referenced below (§3, "end-to-root
> binder" with `binds_overhang_id`) was **removed**. Direct connections (root-to-root +
> end-to-root) are now ONE non-consuming, relocated `OverhangBinding` — BOTH overhangs stay
> in `design.overhangs` (so neither disappears from the sidebar list), each keeping its own
> sequence. See [[overhang-connections-panel]] "★ UNIFIED DIRECT CONNECTIONS". The §3
> auto-assign still applies to LINKER complements + standalone OH_BINDER strands.

User ask: connected overhangs must still appear in the sidebar with correct
sequences; overhangs with sequences must show their bases under the "show base
sequences" toggle in BOTH 3D and the cadnano editor; the sequences must be real
(usable in oxDNA/atomistic sim). Four gaps found + fixed.

## 1. Assembled-sequence helper (sub-domain blind spot)
The sidebar (`overhang_sequences_panel.js`) and the 3D overlay
(`sequence_overlay.js`) read **only top-level `ovhg.sequence`** — so an overhang
sequenced via split sub-domain `sequence_override`s showed BLANK. Backend truth is
`sequences._assemble_overhang_5to3` (sub-domain overrides → parent slice → N).
- **NEW pure JS mirror** `assembleOverhangSequence(ovhg, domainLen?)` +
  `overhangHasSequenceOverride(ovhg)` in
  [design_queries.js](frontend/src/scene/design_queries.js) (vitest in
  `design_queries.test.js`). domainLen defaults to Σ sub-domain length_bp (else
  parent length).
- Sidebar: shows the assembled seq; when any sub-domain has an override the
  Sequence field is **read-only** (+ Gen hidden, Set sends label only) — edit per
  sub-domain in the Domain Designer.
- 3D overlay: overhang letter map built from `assembleOverhangSequence` (was
  `ovhg.sequence`).

## 2. Cadnano base display (was completely absent)
`cadnano_view.js._enableSideEffects()` force-set `showSequences=false` on entry
(the doc comment claimed it "enables" the overlay — it was stale/inverted), so the
cadnano editor had **no base-sequence display at all**. Made `_enableSideEffects`
/ `_restoreSideEffects` **no-ops** + removed `_savedShowSeq`. The overlay already
gets remapped to the flat cadnano bead positions unconditionally by
`reapplyPositions` / the entry+exit animations, and its letter quads face +X (the
ortho camera's view axis, `DoubleSide`), so letters render correctly in 2D. Rule
doc [.claude/rules/cadnano-2d.md](.claude/rules/cadnano-2d.md) updated.
- **Caveat (not yet tuned):** `_SPRITE_SIZE = 0.55 nm` > cadnano bp pitch
  (`BDNA_RISE_PER_BP = 0.334 nm`), so letters overlap somewhat along a helix in the
  flat layout. Readable but dense; shrink `_SPRITE_SIZE` (or add a cadnano-specific
  scale) if it bothers. The Playwright screenshot looked oversized only because the
  test didn't reframe the ortho camera (`f`).

## 3. Auto-assign on connect/set (simulation-real)
Overhang bases are real immediately, but the **linker-complement** and
**end-to-root binder** strands (`Domain.binds_overhang_id`, set by
`_make_complement_domain(dom, overhang_id)` at lattice.py:4526-27 — so the old
"linker strands stay N" memory note was STALE) only get their real reverse-
complement when `assign_staple_sequences` runs. NEW
`sequences.reassign_if_sequenced(design)` = run `assign_staple_sequences` IFF the
scaffold already carries a sequence (no-op otherwise — nothing to pair against),
wired into `create_overhang_connection`, `apply_connection_version` (after
materialize), and `patch_overhang` (sequence-set branch, which clears the parent
strand seq). So connecting / applying / setting auto-propagates real bases; the
oxDNA/atomistic exporters read `strand.sequence`. The ds-linker **bridge** half
(on the virtual `__lnk__` helix) is still N unless `bridge_sequence` is set — a
separate concern, NOT covered here.

## Tests / verification
- Backend: `tests/test_overhang_sequence_propagation.py` (4: connect-propagates,
  no-op-when-unsequenced guard, end-to-root binder, patch re-derive). `just test`
  **3386 passed**.
- Frontend: `design_queries.test.js` (+8 assembleOverhangSequence/override).
  `just test-frontend` 1804 pass (only the pre-existing `keyboard_shortcuts`
  number-hotkey flake fails).
- In-app (Playwright `e2e/connected_overhang_sequences.spec.js`, sanctioned
  troubleshooting use): loads `workspace/playwright_tests/connected_overhangs_seq.nadoc`
  (2 overhangs ACGTACGT/TTTTGGGG + ds linker, complements auto-assigned to RC
  ACGTACGT/CCCCAAAA), asserts both seqs in the sidebar + letter instances > 0 in
  3D AND cadnano. Screenshots `seq_overhang_{3d,cadnano}.png`.

Related: [[overhang-connections-panel]] (connection flows), [[overhang_connections]]
(linker model), [[oh_binder]] (binds_overhang_id).
