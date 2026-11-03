---
name: extra-base-spacing
description: "MD-measured interhelical spacing vs crossover extra-base count (0/1/2), and the View ▸ Adjust for Extra Bases display toggle built on it. The 2.25 nm caDNAno lattice is ~2 A tighter than equilibrium even with NO inserts."
metadata:
  node_type: memory
  type: project
---

# Extra bases widen the lattice — measured, and wired to a view toggle

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**The headline, and it is bigger than the extra-base effect: a relaxed origami sits ~2 Å wider
than the 2.25 nm caDNAno lattice it is BUILT on, even with zero extra bases.** Every design in
NADOC is therefore displayed ~9 % denser than it actually equilibrates. Extra bases add a further,
strongly **sub-linear** expansion on top. This is the frame to read any clash/declash result in:
a large part of what reads as "clashing" is the built lattice being tighter than B-DNA equilibrium,
not the inserts.

<a id="the-measurement-2026-08-05"></a>
- [The measurement (2026-08-05)](details/project_extra_base_spacing/01-the-measurement-2026-08-05.md#the-measurement-2026-08-05)

<a id="method-scriptsmeasure_interhelical_spacingpy"></a>
- [Method (`scripts/measure_interhelical_spacing.py`)](details/project_extra_base_spacing/01-the-measurement-2026-08-05.md#method-scriptsmeasure_interhelical_spacingpy)

## Trap: most of these trajectories are NOT equilibrated

Quintile drift over each run:

| run | drift | verdict |
|---|---|---|
| `24hb_0xT` 50 ns k0 | 24.02 → 25.09 (+1.07) | **still expanding at 50 ns** |
| `24hb_2xT` 2 ns k0 | 24.20 → 24.63 (+0.44) | still expanding |
| `6hbx100_noT` 20 ns k0 | 24.33 → 24.68 (+0.35) | near plateau |
| `24hb_1xT` 5 ns k0 | flat at 26.49 | converged |
| `6hbx100_1xT` 0.5 ns k0 ×3 | flat at 25.0–25.2 | converged |

The flat ones are flat because they *continue* an already-equilibrated predecessor; the fresh ones
are still swelling. **This is why the free-production column cannot be compared across variants**
(24hb reads 0xT 25.01 / 1xT 26.48 / 2xT 24.57 — non-monotonic, purely a run-length artefact) and
why the matched MGHH stage is the number of record despite being under-relaxed in absolute terms.
Both matched-stage series agree on sign and rough magnitude, which is the real evidence.

Honest uncertainty on a Δ is **~±0.3 Å** — from the replica spread (3 × `6hbx100_1xT`: 25.01 /
25.21 / 25.09) and the stage-to-stage spread within one design — not the ±0.01–0.05 Å block SEM,
which only measures within-trajectory noise.

<a id="what-shipped--view--adjust-for-extra-bases"></a>
- [What shipped — View ▸ Adjust for Extra Bases](details/project_extra_base_spacing/02-what-shipped--view--adjust-for-extra-bases.md#what-shipped--view--adjust-for-extra-bases)

## Extra-base positions are a READ of the CG representation (2026-08-05 purge)

**Everything that modified an extra base's 3D position after placement has been deleted**, and so
has the prose that described how one ought to sit. The gap between what was intended and what came
out kept widening with each attempt to specify it, so the specification was removed instead.

What the builder does now: stamp each insert's atoms on the quadratic Bezier between its two
junction nucleotides' **CG backbone positions** — same endpoints, same bow as
`crossover_connections.js` — and minimise only the phosphodiester linker. Nothing moves the residue
afterwards. Verified on 6hbx100_2xT: all 120 insert origins sit on the CG chord to **0.000000 Å**
(rigid-body fit of the ribose template; `test_extra_bases_are_placed_from_the_cg_representation`).

Deleted: `extra_base_repair.py` (the catenation re-placement ladder), `_minimize_{1,2,3}_extra_base`
and their rigid-body machinery, the `_XB_CACHE`, the `z_sign`/`target_c1n` glycosidic swing and its
static repulsion snapshot, `solve_extra_base_pose`, `GET /design/extra-base-seed`,
`designRenderer.setSeedExtraBases` and the CG insert pinning. −1735 lines.

**One thing deliberately NOT routed through CG:** the oxDNA/trajectory override path still takes its
chain direction from the real C3′/C5′ **atoms** (`chain_p0`/`chain_p1`). It orients a nucleotide
from measured `a1` against its bonded neighbours — a fact about atoms, not about where a bead is
drawn. Routing it through CG silently broke
`test_heavy_rep_extra_base_uses_full_simulated_orientation`; that test is the guard.

<a id="-consequence-a-linked-junction-is-now-refused-not-repaired"></a>
- [⚠ Consequence: a linked junction is now REFUSED, not repaired](details/project_extra_base_spacing/03-consequence-a-linked-junction-is-now-refused-not-repaired.md#-consequence-a-linked-junction-is-now-refused-not-repaired)

<a id="opt-in-seed-pre-expansion-seed_lattice_nm--still-live"></a>
- [Opt-in seed pre-expansion (`seed_lattice_nm`) — still live](details/project_extra_base_spacing/03-consequence-a-linked-junction-is-now-refused-not-repaired.md#opt-in-seed-pre-expansion-seed_lattice_nm--still-live)

<a id="the-atomistic-reps-show-the-md-seed--still-live"></a>
- [The ATOMISTIC reps show the MD seed — still live](details/project_extra_base_spacing/03-consequence-a-linked-junction-is-now-refused-not-repaired.md#the-atomistic-reps-show-the-md-seed--still-live)

<a id="-pre-existing-returning-to-t0-flattens-the-insert-chain-0168-nm"></a>
- [⚠ Pre-existing: returning to t=0 FLATTENS the insert chain (0.168 nm)](details/project_extra_base_spacing/03-consequence-a-linked-junction-is-now-refused-not-repaired.md#-pre-existing-returning-to-t0-flattens-the-insert-chain-0168-nm)

<a id="the-cg-bead--atomistic-5-å-register-gap--diagnosed-2026-08-05"></a>
- [The CG bead / atomistic ~5 Å register gap — DIAGNOSED 2026-08-05](details/project_extra_base_spacing/03-consequence-a-linked-junction-is-now-refused-not-repaired.md#the-cg-bead--atomistic-5-å-register-gap--diagnosed-2026-08-05)

## Open

- **The 2-base value rests on one matched comparison per design, both under-relaxed.** A longer
  `24hb_2xT` run and a k0 production for `6hbx100_2xT` would pin it. Deferred by choice.
- Whether the 0-base baseline (2.45 nm) should become the *build* lattice rather than a view
  toggle is untouched — that would change every design's geometry, not just its display, and
  `HONEYCOMB_LATTICE_RADIUS` is a locked constant.

<a id="related"></a>
- [Related](details/project_extra_base_spacing/04-related.md#related)
