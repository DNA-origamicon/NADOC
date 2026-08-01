---
name: overhang-sequence-display
description: Overhang sequence ASSEMBLY + display of record. One assembler per side — assembleOverhangSequence (JS) / _assemble_overhang_5to3 (Py) — feeding the sidebar, the connections panel, the 3D letter overlay and cadnano. Shipped 2026-06-29; probed live 2026-07-31. Rank P2 — three consumers still bypass the assembler or its length source.
metadata: 
  node_type: memory
  type: project
  originSessionId: 77880eb1-e9cc-402f-9567-1e823c0634a5
---

# Overhang sequence assembly + display

**Status: SHIPPED (2026-06-29), re-probed 2026-07-31 — every anchor alive.**
**Rank: P2 — the assembler itself is correct and is the single source of truth on both
sides; what's left is three consumers that never migrated onto it (display-only
correctness, no topology risk).**

There is exactly **one assembler per side**, and they agree:

| Side | Function | Rule |
|---|---|---|
| JS | `assembleOverhangSequence(ovhg, domainLen)` [design_queries.js:144](frontend/src/scene/design_queries.js#L144) | sub-domain `sequence_override`s → parent slice → pad `N` |
| Py | `_assemble_overhang_5to3(spec, domain_len)` [sequences.py:410](backend/core/sequences.py#L410) | same, mirrored deliberately |

**The length argument is the whole subtlety.** `assembleOverhangSequence`'s own default
is *nominal* — Σ sub-domain `length_bp`, else `parent.sequence.length` — which is **stale
after a drag-resize**. The authoritative current length is the **backing domain**:

```js
// design_queries.js:122  overhangDomainLength(design, ovhgId)
if (d.overhang_id === ovhgId) return Math.abs(d.end_bp - d.start_bp) + 1
```

Backend twin: `duplex.overhang_offset_bases` [duplex.py:122](backend/core/duplex.py#L122) —
`abs(dom.end_bp - dom.start_bp) + 1`, same formula, and its docstring names the JS mirror.
**Every caller must pass `overhangDomainLength(...)` as the 2nd arg.** One production
caller doesn't (open item 1).

## Code locations (probed 2026-07-31)

| What | Where | Note |
|---|---|---|
| Assembler + override predicate | `design_queries.js:144` / `:174` | `overhangHasSequenceOverride` has exactly 1 prod caller |
| Authoritative length | `design_queries.js:122` | 2 prod importers + 7 internal sites |
| Pairing helpers | `pairingSegments:219`, `isComplement:195` | `pairingSegments` → connections panel only; `isComplement` → `ui/strand_sequence_pairing.js:57` only |
| Sidebar | [overhang_sequences_panel.js:230-242](frontend/src/ui/overhang_sequences_panel.js#L230) | assembled seq; `readOnly` + Gen hidden + Set-sends-label-only when per-sub-domain — all three still hold |
| Connections panel | `ui/overhang_connections_panel.js:874,1458,1508` | passes `overhangDomainLength` correctly |
| 3D letter overlay | [sequence_overlay.js:226-228](frontend/src/scene/sequence_overlay.js#L226) | `_SPRITE_SIZE = 0.55` at `:23`, one shared `PlaneGeometry` `:58` |
| Cadnano display | `scene/cadnano_view.js:402-403` | `_enableSideEffects`/`_restoreSideEffects` still empty no-ops; `_savedShowSeq` gone; nothing forces `showSequences=false` |
| Targeted re-derive | `sequences.reassign_strands:706` + `overhang_dependent_strand_ids:674` | 4 / 3 call sites in `crud.py` |
| The 3 hooks | `patch_overhang` [crud.py:5009](backend/api/crud.py#L5009), `create_overhang_connection` `:7240`, `apply_connection_version` `:7787` | all three targeted; headless wrappers for 2 of 3 (`headless_build.py:990`, `:1043`) |
| Linker complement | `_make_complement_domain` [lattice.py:4090](backend/core/lattice.py#L4090) sets `binds_overhang_id` (`:4111`); `Domain.binds_overhang_id` `models.py:863` | 4 callers |
| ds-linker bridge half | `_bridge_sequence_padded` [assembly_linker.py:91](backend/core/assembly_linker.py#L91) | unset bridge is still `"N" * linker_bp` — deliberate, separate concern |

**Tests (counted, not remembered):** `tests/test_overhang_sequence_propagation.py` = **3**
(the doc long said 4), `tests/test_targeted_reassign.py` = **9**, none `slow`; also
`tests/test_assign_staple_preserves_overhang_seq.py`. Frontend: `design_queries.test.js`
= **53** `it(`, of which **9** cover the two assembly symbols — and it is the *only*
frontend file that mentions them. E2E: `frontend/e2e/connected_overhang_sequences.spec.js`
(the doc said `e2e/`), fixture `workspace/playwright_tests/connected_overhangs_seq.nadoc`
present.

**No supersession.** `overhang_generator.py:288/:384` are random-sequence *generators*, not
assemblers; `crud.py:7454 _cv_sequence_for_live_overhang` and `:1571
_backfill_overhang_sequences` are connection-version/migration helpers. Nothing has taken
over.

## Open items (live, 2026-07-31)

1. **The 3D overlay drops the length argument — do this first.**
   `sequence_overlay.js:227` calls bare `assembleOverhangSequence(ovhg)`, so after a user
   drags an overhang end longer, the sidebar and the connections preview show the grown
   `N`-tail while the 3D letters silently draw only the shorter *nominal* run. Every other
   production caller threads `overhangDomainLength(design, ovhg.id)`. One-line fix; the
   `overhangDomainLength` docstring (`design_queries.js:110-116`) already *claims* the
   overlay is a consumer — it isn't.
2. **`ui/overhangs_manager_popup.js:529`** (`_selectedOverhangSequence`) returns raw
   `o.sequence ?? null` and imports nothing from `design_queries.js` → a per-sub-domain-
   sequenced overhang reads BLANK in the CT / linker-bridge RC mirror. Exactly the bug §1
   fixed for the sidebar, never applied here.
3. **`ui/assembly_overhangs_manager_popup.js:494,694-695,770,833`** all read raw
   `ovhg.sequence`, and `_overhangLengthBp` (`:986-989`) is a **third** length formula
   (Σ `sub_domains.length_bp` only, no backing-domain fallback) that disagrees with both
   `overhangDomainLength` and `duplex.overhang_offset_bases` for an overhang with no
   sub-domains.
4. **`_SPRITE_SIZE = 0.55 nm` is still untuned for cadnano** (bp pitch there is
   `BDNA_RISE_PER_BP = 0.334`), so letters overlap along a helix in the flat 2D layout.
   Readable but dense. There is still no cadnano-specific sprite scale — `sequence_overlay.js`
   contains no `cadnano` token at all. Cosmetic; reframe the ortho camera (`f`) before
   judging a screenshot.
5. **Different-length direct connect stays UI-only.** `crud.py:7647` skips the binding with
   the comment *"the duplex is created separately by the frontend's `_ensureDuplexForPair`"* —
   a headless hole owned by [[overhang-connections-panel]], noted here only because it is on
   this doc's surface.

**Closed since written:** the end-to-root binder *splice* (§3's `binds_overhang_id` path as
originally described) was removed 2026-06-30 — direct connections are now ONE non-consuming
relocated `OverhangBinding`, both overhangs stay in `design.overhangs`, each keeping its own
sequence (see [[overhang-connections-panel]] "★ UNIFIED DIRECT CONNECTIONS"). Auto-assign
still applies to LINKER complements + standalone OH_BINDER strands. And the three auto-assign
hooks became **targeted** on 2026-07-27 (`reassign_strands` over
`overhang_dependent_strand_ids`) because the old design-wide `reassign_if_sequenced` silently
destroyed hand-typed staple sequences; pinned by `tests/test_targeted_reassign.py`. The
EXPLICIT bulk commands (`assign-staple-sequences`, `full-autostaple`) are still design-wide
and DO overwrite a manual sequence — both push an undo snapshot. See
[[project_strand_sequence_edit]].

**Dead:** `sequences.reassign_if_sequenced:742` has **zero callers repo-wide** — the old
"still exists for headless/ML callers" note was aspirational. Logged in
[[project_tech_debt]].

Related: [[overhang-connections-panel]] (connection flows), [[overhang_connections]]
(linker model), [[oh_binder]] (`binds_overhang_id`), [[project_overhang_subdomains]]
(where per-sub-domain sequences are edited).
