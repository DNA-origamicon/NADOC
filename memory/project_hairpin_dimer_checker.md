---
name: hairpin-dimer-checker
description: "Hairpin/self-dimer Tm checker (primer3, origami buffer 0 Na⁺/10 mM Mg²⁺/200 nM) for overhangs + linker strands; Tools→Sequencing TOGGLE + '0' (live re-check while on); clickable ⚠ → IDT-style structure window in 3D view, cadnano path view, spreadsheet, Plates & tubes, Overhang Connections; auto-check after overhang generation. SHIPPED 2026-09-18."
metadata:
  type: project
  status: shipped
  authority: canonical
---

# Hairpin/Dimer Checker — SHIPPED 2026-09-18

Flags hairpin or self-dimer **Tm > 30 °C** (user-specified threshold, strict `>`). **Two levels
(user-specified 2026-09-18):** amber ⚠ `warning` for 30 < Tm ≤ 50 °C, red ⚠ `critical` for
Tm > 50 °C. Backend sets `check.severity` + `report.severe_threshold_c` / `summary.critical`
(`DEFAULT_SEVERE_C`, API `severe_threshold_c`); frontend `hairpinDimerLevel(checks)` takes a
strand's worst level; colours `HAIRPIN_DIMER_COLORS` {warning #d29922, critical #f85149} (3D /
path-view glyph amber stays #f5a623). Every surface, window caption and toast is tiered.

## Scope decision (made without the user; revisit if they disagree)

- **Overhang strands:** only each overhang's ssDNA bases (assembled exactly like
  `sequences._assemble_overhang_5to3`), not the scaffold-bound body. Rationale: the body is
  duplexed after folding and fixed by the scaffold. Whole-strand analysis flagged ~96% of random
  60-mers (2–3 bp stems, ΔG₃₇≈0 still have two-state Tm > 30 °C) → useless. Checks: hairpin,
  self-dimer (copy×copy), and a cross-dimer for every overhang pair on one strand.
- **Linker strands** (`StrandType.LINKER`): whole strand = WC complement of bound overhang bases
  (bp-aligned) + `OverhangConnection.bridge_sequence` (RC on the ds `b` half). Stored linker
  `strand.sequence` has N across the bridge — the backend never writes bridge bases there.
- OH_BINDER strands and strand extensions are NOT checked (not requested).

## Thermodynamics

primer3-py `thal` (dependency added 2026-09-18). **Default conditions = DNA-origami folding buffer
(user-specified 2026-09-18): 0 mM NaCl, 10 mM MgCl₂, 200 nM oligo**, 0 dNTP, ΔG at 37 °C
(`hairpin_dimer.ORIGAMI_BUFFER`). Deliberately NOT `design.tm_settings` (50 mM Na⁺/250 nM, still used
by sub-domain Tm annotations). API body may override `na_mM`/`mg_mM`/`conc_nM` (IDT defaults:
50/0/250); Na⁺ + Mg²⁺ = 0 is rejected (primer3 returns Tm −273 °C). thal caps a
sequence at 60 nt → 60-nt windows / 10-nt stride (structures spanning ≤51 nt exact). N splits
into A/C/G/T runs (≥4 nt); status `unsequenced` (no defined base) / `partial` / `checked`.
Negative Tm values are real two-state extrapolations of very unstable structures, never flagged.

## Code

- Backend: `backend/core/hairpin_dimer.py` (`check_design`, `hairpin`, `dimer`,
  `linker_strand_sequence`, `domains_signature`); read-only `POST /design/hairpin-dimer-check`
  (`routes_hairpin_dimer.py`, body `{overhang_ids?, strand_ids?, threshold_c?}`).
  `generate-overhang-sequences` now also returns `generated_overhang_ids`.
- Frontend pure: `ui/hairpin_dimer_report.js` — merge, staleness, index, text, ⚠ badge.
  **Staleness contract:** each check records `inputs` (assembled overhang bases, bridge, linker
  `domains_signature` string); a check whose inputs differ from the live design is dropped at once
  (no stale ⚠), and while the toggle is on it is re-checked. Frontend + backend pin the format.
- Frontend factory: `ui/hairpin_dimer_checker.js` — a **toggle** (menu pill + '0'; persisted in
  localStorage `nadoc.hairpinDimer.active`, default OFF; mirrored to other tabs via broadcast
  `hairpin-dimer-toggle`). ON: full check, then LIVE — every design change schedules a debounced
  (400 ms) partial re-check of overhangs/linkers whose check is missing or stale
  (`hairpinDimerRecheckTargets`); defers while another check is in flight so a generation isn't
  checked twice. It publishes `hairpinDimerReport` only while ON (null → every ⚠ hides). The
  generation hook (`onOverhangSequencesGenerated`, both API layers) ALWAYS runs; while OFF its
  warning toast points to the toggle (user's original "automatic on generation" requirement).
- Surfaces: spreadsheet ID cell (both editors), `plate_view` `warning` record field +
  `setWarnings()` (no re-layout), Overhang Connections dropdown options / per-side line / list rows
  (right sidebar **Overhangs** tab). Assembly mode: NOT wired.
- **3D view:** `scene/hairpin_dimer_markers.js` — DOM ⚠ buttons in a layer over `#canvas-area`
  (not sprites: native click/tooltip, no pick-pipeline changes; the orbit relay ignores gestures not
  started on #canvas). One per flagged strand (`hairpinDimerMarkers()`: flagged overhang's backing
  domain, or a linker's domains); `refresh()` in main.js `tick()` averages LIVE bead positions via
  `helixCtrl.lookupEntry('helix:bp:dir')`, static geometry fallback. Hidden in assembly mode.
  Gotcha: VoltronCore's geometry arrives ~10 s after the design — markers appear then.
- **cadnano path view:** `cadnano-editor/pathview/hairpin_dimer_markers.js` (place/draw/hit, pure);
  pathview gained `setHairpinDimerMarkers()` + `onHairpinDimerClick(strandId, label)` (render-only:
  it reports, main.js opens the window) and a canvas `title` hover tooltip.
- **Click a ⚠ → IDT-style window** (`ui/hairpin_dimer_window.js`, `createModal`): per flagged
  check, the hairpin drawn as a stem–loop and dimers as an aligned duplex
  (`ui/hairpin_dimer_structure.js`, pure SVG from primer3's ASCII — pairs by slash matching; thal
  hairpins are single stem–loops with bulges/internal loops, so a ladder + loop-circle layout is
  complete; tails > 8 nt elided with "5′ +N nt"). Plate badge click = `plate_view`
  `onWarningClick(strandId, name)`; option `<option>` ⚠ is not clickable (use the line under it).

## Verified

23 pytest (`tests/test_hairpin_dimer.py`), vitest: report/structure/window/checker(toggle, live,
dedupe, tiers)/3D markers/pathview markers/spreadsheet×2/plate_view/plates_tab/oconn panel/keyboard.
Tiers in-app on VoltronCore: 3 red (51.0/52.0/66.6 °C) + 2 amber (42.5/44.0 °C), identical across
3D, cadnano, spreadsheet, plate badges, oconn options, window captions. Structure oracle = the user's IDT screenshot of
TACACGTCCCCATGGGGACGTGTA (same 9 pairs, 6 G·C + 3 A·T, CATG loop). In-app Playwright on an
isolated backend (`NADOC_WORKSPACE` scratch) with a VoltronCore copy: 70 checks, 5 flagged; every
⚠ surface opens the window in both editors; toggle on/off incl. cross-tab; 3D ⚠ click leaves
the selection unchanged; regenerating a flagged overhang = one targeted re-check. ΔG differs from IDT's UNAFold (−12.8 vs primer3
−10.7 kcal/mol at 25 °C, 50 mM Na⁺) — different loop/terminal parameters; structures agree.

## Generation screening — shipped 2026-09-22

- Generation now screens full overhangs, whole affected staples, and final connected linker
  sequences through `overhang_sequence_screen.OverhangSequenceScreen` before committing.
  Single Gen, bulk Gen and sub-domain Gen share the screen. Overhang/linker cutoff is 30 °C
  under `ORIGAMI_BUFFER`; staple hairpin and self-dimer limits are each max(30 °C, fixed-body
  baseline with the variable overhang masked). The baseline allows immutable scaffold-body
  structures without grandfathering the old overhang. It bounds maximum Tm per structure type;
  it does not prove that every individual structure is unchanged. Locked sub-domains survive.
  Accepted staple/linker sequences are committed together, including actual bridge bases.
  Johnson candidates are tried first; random exploration remains subject to the same screen
  and GC/heuristic filters. Exhaustion is a 422 with no mutation, never an unchecked fallback.
  All-or-nothing bulk generation screens against previously accepted candidates in the batch.
  Limits: unchanged linker arms/bridge can make one-arm regeneration impossible, undefined
  bases remain partial, and long-strand windowing is inherited from the checker.

Validation: 33 tests in `test_hairpin_dimer.py`, 69 focused backend tests, and
6,590 frontend tests passed. The real Gen button cleared an 85.8 °C linker warning
on an isolated VoltronCoreArmV2 copy and the saved source remained unchanged.
The wider FAST run still has 30 failures and 9 errors outside the generation tests;
the FULL suite is deferred. Details: [generation screening](../docs/overhang_generation_screening.md).

## Open

- No UI to change threshold/conditions. The checker supports API-body overrides;
  generation uses its fixed defaults (30 °C, origami buffer).
