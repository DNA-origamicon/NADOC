# exp46 — MD-adjusted placement of single extra bases at Holliday junctions

**Source data:** job `29c5b267380f` — `2hb_1xT`, 200 ns free (k = 0) NPT, 4 fs + HMR,
50 M steps completed 2026-07-29, 20 000 frames at 10 ps, 21 436 atoms.  Analysed at
50 ps sampling (4 000 samples).  `2hb_1xT` is the minimal Holliday-junction model: two
helices, ONE reciprocal crossover pair (bp 13 / bp 14, 3′ exits on opposite helices),
one unpaired T on **each** crossover — i.e. the "extra bases on **both** crossovers" case.

## The frame everything is reported in

NADOC's builder (`atomistic._build_extra_base_atoms`) places insert *i* of *n* on a
quadratic Bezier from `p0 = C3'(src)` to `p1 = C5'(dst)`, control point
`mid + bow_dir · 0.3 L`, at `t = i/(n+1)`; `bow_dir = cross(half_a → half_b, avg_axis)`.

Measurements use the same frame but with the bow referenced to the **chemical hop**
(3′ exit → 5′ entry) rather than to `half_a → half_b`:

```
u    = unit(C5'(dst) − C3'(src))              the chord
bow  = unit(cross(unit(src→dst), avg_axis))   perpendicular to u
ax   = cross(u, bow)
```

`half_a`/`half_b` is only the order the `Crossover` record stores its halves in, so the
builder's bow side is arbitrary per crossover.  The hop is intrinsic, and it runs
opposite ways on the two crossovers of a reciprocal pair — which is what lets one set of
constants describe both.  Coordinates are fractions of the chord length L (9.0–9.3 Å).

## Result — the equilibrium pose

Window 20–180 ns (head = equilibration; see caveats for why the tail is not used).

| | insert @ bp 13 | insert @ bp 14 | pooled |
|---|---|---|---|
| **t** (along chord) | +0.536 ± 0.035 | +0.598 ± 0.051 | **+0.567 ± 0.053** |
| **bow** | −0.269 ± 0.070 | −0.345 ± 0.127 | **−0.307 ± 0.110** |
| **ax** | −0.211 ± 0.124 | +0.300 ± 0.150 | \|ax\| 0.27 (sign does not transfer) |
| chord L | 9.26 Å | 8.97 Å | |

Positions are of **C1′**.  The phosphate stays near the 3′ end of the chord
(t = 0.17 ± 0.05, bow = −0.17); the base centroid sits further out (bow = −0.43/−0.61).

**The bow coordinate is negative in 100 % of frames for both inserts, in every
sub-window tested** (20–100, 20–180, 100–180 ns give pooled bow −0.303 / −0.307 / −0.312
and t +0.557 / +0.567 / +0.577).  Physically: the two inserts sit on **opposite** faces
of the inter-helix plane — one 6.8 Å out, the other 1.5 Å out, measured from the junction
centre — which in hop-referenced terms is the same side for both.

## What the build currently produces

| stage | bp 13: t / bow / ax | bp 14: t / bow / ax |
|---|---|---|
| pure Bezier arc pose (`fast_bridges`) | 0.716 / **+0.647** / −0.199 | 0.789 / −0.674 / +0.193 |
| full build (joint solve + repair) | 0.647 / −0.279 / −0.272 | 0.634 / −0.229 / +0.259 |
| package seed (after declash relax) | 0.640 / −0.189 / −0.409 | 0.689 / −0.176 / +0.547 |
| **MD 20–180 ns** | **0.536 / −0.269 / −0.211** | **0.598 / −0.345 / +0.300** |

Three findings:

1. **The arc SEED is on the wrong side for exactly half of all extra-base crossovers.**
   `bow_dir` comes from `half_a → half_b`, so the sign is arbitrary: the bp 13 insert is
   seeded at bow **+0.647** where equilibrium is −0.269 — 8.4 Å away, on the far face.
   Counted across designs, `half_a` is not the 3′ exit for 1/2 (2hb), 12/24 (6hb_2xT) and
   30/60 (6hbx100) extra-base crossovers.  Consequence: **the builder seeds both inserts
   of every reciprocal pair on the same physical side** — a mutually overlapping,
   frustrated pose.  Verified on every reciprocal insert pair of 2hb_1xT, 2hb_2xT,
   6hb_2xT, 6hbS42_1xT, 6hbx100_1xT (28/28) and 6hbx100_2xT.
2. **The arc seed also bows about twice too far** (|bow| 0.65–0.67 vs 0.31) and sits
   0.15–0.22 L too far toward the 5′ entry (t 0.72–0.79 vs 0.57).
3. **The `ax` coordinate is already right** — the arc rule gives −0.199/+0.193 where MD
   gives −0.211/+0.300, sign included.  No axial correction is needed.

**The joint solve already recovers all of this.** Distance from the delivered (post-solve,
post-repair) C1′ to the MD mean, over (t, bow, ax) × L:

| variant | bp 13 | bp 14 |
|---|---|---|
| pure arc seed | 8.77 Å | 3.85 Å |
| **full build (shipped)** | **1.18 Å** | **0.97 Å** |
| the MD ensemble's own thermal spread | 1.51 Å | 1.99 Å |

**The shipped geometry is already inside the thermal spread of the equilibrium ensemble.**
What is badly wrong is only the *seed* the solve starts from.

## Adjusted placement to use

Bottom line first: **the pose NADOC ships needs no adjustment** — it is already inside the
equilibrium ensemble's thermal spread.  What is worth adjusting is the *seed's bow side*,
for the sake of catenation (next section), not for the sake of the final geometry.

For a single unpaired base at a crossover, target **C1′** at

```
t   = 0.57      along C3'(src) → C5'(dst)
bow = −0.31     i.e. 2.8 Å along cross(avg_axis, hop)   [NOTE the sign]
ax  =  as the current arc rule already produces (|ax| ≈ 0.27, sign correct)
```

with the phosphate at t = 0.17, bow = −0.17.  Apply per crossover; because the bow is
hop-referenced, the two crossovers of a reciprocal pair then automatically land on
opposite sides, which is what the ensemble shows.

**Do not bake in a base orientation.** The two inserts' whole-nucleotide orientations
differ by **103°** (per-insert spread 18° and 26°, p90 28°/45°), and the glycosidic and
ring-normal projections disagree between them.  A single unpaired base at a junction is
a soft, multi-modal degree of freedom; the existing glycosidic rule plus the bridge solve
is the right level of commitment.

## Independent confirmation: the MD side is the side that stops catenating

The bow side can be set without touching any source, by choosing which half of the
`Crossover` record is stored as `half_a` (the builder bows along
`cross(half_a → half_b, avg_axis)`): `half_a = dst` gives `bow = −cross(hop, axis)` (the
MD side), `half_a = src` gives `+cross(hop, axis)`.  Screened against the catenation
detector with the repair ladder disabled — i.e. the RAW build
(`hop_bow_experiment.py`; catenated reciprocal insert pairs):

| design | inserts/crossover | today | **−cross(hop,axis)  [MD side]** | +cross(hop,axis) |
|---|---|---|---|---|
| 2hb_1xT | 1 | 1 / 1 | **0 / 1** | 1 / 1 |
| 6hbS42_1xT | 1 | 1 / 3 | **0 / 3** | 3 / 3 |
| 6hbx100_1xT | 1 | 15 / 28 | **2 / 28** | 22 / 28 |
| 24hb_1xT | 1 | 65 / 159 | **5 / 159** | 89 / 159 |
| 2hb_2xT | 2 | 1 / 1 | 1 / 1 | **0 / 1** |
| 6hb_2xT | 2 | 10 / 10 | 8 / 10 | **0 / 10** |
| 6hbx100_2xT | 2 | 26 / 28 | 17 / 28 | **0 / 28** |

**For a single insert, seeding on the side the 200 ns ensemble picks cuts raw catenation
by ~93 % (24hb_1xT 65 → 5 of 159 pairs; 6hbx100_1xT 15 → 2 of 28).**  Two independent
criteria — the equilibrium ensemble, and topological linking of the L-BFGS-B linker solve
— agree on the same side.  That is the strongest evidence in this study, and it makes the
repair ladder nearly unnecessary for 1xT designs.

**The correct side flips with insert count.**  For two inserts per crossover the *other*
side is the clean one (37 → 0 pairs across the three 2xT designs).  Physically reasonable
— two stacked inserts occupy the gap differently — but there is **no MD for 2xT**, so this
is a solver observation only.  The constant is per-insert-count.

**But the side fix cannot simply be shipped.**  With the MD-side seed the *post-solve*
pose moves AWAY from equilibrium (bp 13: 1.18 Å → 4.88 Å; bp 14: 0.97 Å → 3.05 Å), because
the joint solve's objective and the repair ranking were tuned around today's seed.  The
seed also still lands at roughly twice the equilibrium radius (arc-hop bow −0.37 / −0.67
vs MD −0.29 / −0.32), and that cannot be fixed by tuning `_BOW_FRAC_3D`: ≈0.5 L of the arc
pose's C1′ offset comes from the template **orientation** (`_extra_base_frame` sets
`e_n = bow_dir`) and only 0.15 L from the control point, so the placement would have to be
respecified as a pose.  So: side fix ⇒ far fewer catenated builds; pose fix ⇒ needs the
solve re-tuned.  **That trade-off is the decision, and it is yours.**

## Caveats

* **One trajectory, one junction, one design.** Two inserts, both from the same
  reciprocal pair, seeded from a build that already had them on opposite sides.  The
  trajectory shows that arrangement is stable for 180 ns; it does not prove it is the
  global minimum, and it cannot distinguish "outer" from "inner" insert by any intrinsic
  rule (that assignment was inherited from the seed).
* **The solute is bigger than its periodic box.**  NPT collapsed the cell from
  44.1 × 66.6 × 113.6 Å to 37.6 × 56.7 × 96.7 Å (the carved water shell leaves the box
  corners empty), while the DNA spans 45–55 Å in x.  Measured DNA-to-own-image minimum
  distance: mean 7.0 Å, below 3 Å in 26 % of frames, and **2.2 Å throughout the last
  25 ns** — the construct is in direct contact with its own image for part of the run.
  The reported local pose is window-insensitive so this does not appear to move it, but
  the global splay (helix–axis angle 16–18°, rising to 33° late) and the late fraying are
  suspect.  Relevant to `project_water_shell_carve`: NPT on a carved shell can shrink the
  box below the solute.
* **Base pairing decays late.** 98.7 % of the 42 designed bp intact over 20–180 ns, but
  90.5 % over 180–200 ns (the 7 bp staple arms of this minimal construct fray).  The last
  20 ns is excluded.
* **The "extra base on only ONE crossover" case has no data** — and no design.  Every
  2hb variant is symmetric (`2hb_noT` 0/0, `2hb_1xT` 1/1, `2hb_2xT` 2/2).  The per-crossover
  rule should transfer, because the side is set by the hop and by the partner *backbone*
  (present whether or not it carries an insert; measured insert-to-partner-backbone
  clearance is 3.5 Å and 4.7 Å, i.e. in contact), but that is an argument, not a
  measurement.  **Next experiment:** an asymmetric 2hb (T on the bp 13 crossover only)
  through the same 200 ns protocol.
* No free-MD numbers for **two** inserts per crossover on a verified-unlinked build; the
  24hb_2xT ensemble predates the catenation fix.

## Files

| file | what |
|---|---|
| `xb_map.py` | design ↔ package-PDB/PSF/DCD row map; `FrameJoiner` rebuilds one periodic image from a `wrapAll on` frame (bond-based unwrap + modal base-pair shift — a single-atom minimum image is not enough here) |
| `xb_observables.py` | per-frame junction geometry, hop-referenced coordinates, Kabsch template pose, integrity checks |
| `xb_summary.py` / `xb_recommend.py` / `final_numbers.py` / `show_fixed_frame.py` | reports |
| `bow_sign_vs_catenation.py` | is same-side seeding universal? (yes, 28/28) |
| `hop_bow_experiment.py` | catenation screen with a hop-referenced bow (in-memory half swap; **not** a proposed implementation — see `feedback_crossover_no_reasoning`) |
| `compare_builds_to_md.py` | arc / built / arc-hop / built-hop vs the MD target |
| `2hb_1xT_xb_traj.json` | the 4 000-sample dump |

Integrity of the analysis itself: the two phosphodiester bonds each insert bridges
measure 1.57 ± 0.03 Å across all 4 000 frames, and the template rigid fit has 0.51/0.61 Å
rmsd — the unwrapping and atom mapping are correct.
