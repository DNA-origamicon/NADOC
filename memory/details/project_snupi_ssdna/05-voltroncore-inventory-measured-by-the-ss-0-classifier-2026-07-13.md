# VoltronCore inventory (measured by the SS-0 classifier 2026-07-13 — the sizing target) — supporting detail

[Topic head](../../project_snupi_ssdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## VoltronCore inventory (measured by the SS-0 classifier 2026-07-13 — the sizing target)

`workspace/VoltronCore.nadoc`: 59 helices, 205 strands, **7088 bp FEM nodes / 7040 elements**.
Reproduce with `uv run python scripts/snupi_ssdna_audit.py workspace/VoltronCore.nadoc`.

| Class | Runs | nt | Length histogram |
|---|---|---|---|
| **bridge — cross-helix hop** (load-bearing; SNUPI models it; crude Lp=1.5 spring today) | **35** | **295** | 6×13, 10×13, 8×4, 4×2, 16×2, 15×1 |
| bridge — interior gap (same helix) | 0 | 0 | — |
| **tail — overhang / toehold** (SNUPI *cannot* represent) | **55** | **571** | 3×24, 16×23, 12×5, 28×2, 15×1 |
| tail — dangling scaffold/staple end | 0 | 0 | — |
| free (no meshed neighbour) | 0 | 0 | — |
| Helices with **zero** FEM nodes (pure overhang/reference) | **11** | | |

**Total ssDNA = 866 nt ≈ 11% of the structure by nucleotide, and 66% of it is TAIL** — the case SNUPI
cannot represent at all. This is why the bulk of the plan is SS-2/3/4 (the extension) rather than SS-1
(the gap-closure). The other 34% is cross-helix scaffold hops, which SS-1 upgrades from a crude
`L_p = 1.5 nm` axial spring to the real SNUPI element.

⚠️ **A pre-SS-0 hand-count claimed "275 nt of terminal scaffold on 34 helices + 4 interior gaps". It was
WRONG** — it inferred runs from bp-index ranges instead of walking the strand path. VoltronCore has **no**
dangling scaffold ends and **no** interior gaps; that scaffold ssDNA is all cross-helix hops. Trust the
classifier (`snupi_ssdna.classify_ssdna_runs`), never a bp-range heuristic. (The tail machinery in SS-2/3/4
still handles dangling ends — other designs have them — but VoltronCore's tails are all overhangs.)

At 1 bead/nt, tails add ~571 nodes to 7088 (+8%) — negligible for the coarse-blob hydro path, which
already runs full M13 (7240 nodes) in 1.74 GB. **Do not over-coarsen the tails:** ssDNA `L_p` = 0.67 nm ≈
one nucleotide of contour, so 1 bead/nt is the *physically* right mechanical resolution. (Hydrodynamic
blobbing is a separate, coarser grouping — SS-3.)

### ✅ FIXED in SS-1 — separate bug found by the SS-0 audit: RIGID BEAMS THROUGH VACUUM

VoltronCore has **2 intra-helix duplex beams of 22.1 nm** (`h_XY_1_0` and `h_XY_2_0`, both bp 71→136).
Diagnosed — and it is **not** an ssDNA case at all:

```
h_XY_1_0   bp  60- 71  scaffold+staple   (duplex)
           bp  72- 76  scaffold only     (5 nt — part of a 10-nt ssDNA hop to h_XY_2_0)
           bp  77-130  EMPTY             (54 bp — NO STRAND AT ALL. the helix does not exist here)
           bp 131-135  scaffold only     (5 nt — the return hop)
           bp 136-149  scaffold+staple   (duplex)
```

The scaffold physically *leaves* the helix and comes back. But `build_fem_mesh` sorts the helix's duplex
bp and beams together every consecutive pair, so bp 71 and bp 136 get a **full-stiffness dsDNA beam
spanning 54 bp of vacuum**, rigidly welding two duplex blocks whose only real connection is a 10-nt ssDNA
scaffold hop. Severe over-stiffening, and it is the mesh builder assuming *any two consecutive duplex bp
on a helix are bonded* — an assumption that is simply false.

**Fix (SS-1):** do not emit an intra-helix beam across a stretch with **no strand coverage**. A bp step is
a duplex beam only if the intervening positions are actually occupied; an unoccupied stretch means the two
blocks are separate FEM bodies on the same helix, coupled only through the real ssDNA hops and crossovers.
The existing disconnected-body machinery ([[project_cando_fem]]) covers whatever this disconnects — and
here it disconnects nothing, because the ssDNA hops still couple the blocks. Pin it: a helix with an empty
interior stretch must produce **zero** beams spanning it.

---

## SS-0 — mesh representation + ssDNA audit (no behavior change)

**Goal.** Make the mesh *able* to carry ssDNA nodes, and produce an inventory of every design's ssDNA,
without changing a single solved number.

**Build.**
- `FEMNode.kind: Literal["bp", "ss"] = "bp"`, plus enough provenance on an `ss` node to map it back to a
  render bead: `(helix_id, bp, direction, domain/overhang key, index-along-tail)`. Every existing
  consumer must keep working when it sees only `kind="bp"` (they will — the field defaults).
- A mesh-builder helper that *walks* the strand topology and enumerates the three cases above
  (`classify_ssdna_runs(design) → [SSRun(kind="bridge"|"tail", nts, anchor_node, strand, domain)]`).
  Emission of actual ss nodes is behind a flag that **defaults OFF** — SS-0 ships the classifier, not the
  nodes.
- `scripts/snupi_ssdna_audit.py <design.nadoc>` printing the inventory table above for any design.

**Tail anchor rule (ANSWERED by the user 2026-07-13 — do not re-derive):**

> *The tail anchor is defined by which end has a crossover into the embedded staple.*

An overhang tail is an ssDNA domain hanging off a staple whose other domains are **embedded** in the
duplex core. Walk the strand's domains in path order: the tail's anchor is the meshed duplex node on
whichever side of the ssDNA run **continues into that embedded staple** — i.e. the side where the strand
crosses back into the core. It is **not** fixed to 3′ or 5′; a tail at the strand's 5′ terminus anchors on
its 3′ side and vice versa, and the traversal tells you which. Consequences:
- A tail has **exactly one** meshed neighbour along the strand path. (Two meshed neighbours ⇒ it is a
  *bridge*, not a tail — that is the SS-1 case, and it is how the classifier discriminates them.)
- **Zero** meshed neighbours ⇒ a fully free ssDNA strand, not attached to the core. Excluded from the FEM
  (as today); count it in the audit and report it.
Reuse the existing proven traversal in `_add_ssdna_hops` (prev domain's 3′ exit → next domain's 5′ entry)
rather than deriving polarity independently. Any *further* polarity question → ask, implement nothing.

**Gate.** `build_fem_mesh` output is byte-identical on 6HB, 3x4SQ, and VoltronCore (assert node count,
element count, and a hash of the element list). The audit script reproduces the VoltronCore table above.

**Done.** Classifier + audit + zero behavior change. `just test-smart`.

---

## SS-2 — free ssDNA tails in the dynamics engine

**Goal.** Overhangs and dangling scaffold ends become real, thermally-fluctuating chains — in Langevin only.

**Built — see the ✅ SS-2 section at the top for what actually shipped and the three non-obvious
findings.** The plan below is kept for its reasoning; two of its instructions turned out to be WRONG
and were corrected in flight:

- ~~"chained by ssDNA beams (`ssdna_element(1)` per link)"~~ — **no.** That is the collapsed
  end-to-end element and re-using it per link double-counts the chain's entropy. The link carries the
  intrinsic constants instead (finding 1).
- ~~"Initial tail configuration: the rendered geometry (the overhang's ball-joint pose)"~~ — **no.**
  The rendered pose spaces nucleotides at the 0.34 nm *duplex* rise, half the ssDNA contour per nt, so
  every bond would start compressed ~2× and inject a large spurious axial stress. The chain is laid
  out straight from the anchor at its rest bond length (0.68 nm) instead — ~~the initial pose does not
  survive equilibration anyway, so it never reaches a figure.~~ **That last clause was WRONG and SS-3
  had to fix it:** the initial pose survives all too well. A straight chain is a fully extended rod,
  and collapsing it into a coil is the slow long-wavelength mode finding 3 says MD cannot converge — so
  it stays a rod for the whole run. The straight layout is still the elements' REST state, but the
  chain now *starts* as a thermal coil (`_coil_run`, SS-3), which rigid pivots build out of the rod
  without changing a single bond length.

The rest held: one bead per nt; the tail block enters **only** the dynamics force/mass path and is
assembled by the dynamics module, never by `build_fem_mesh`'s K path (decision 1, enforced
structurally and pinned).

**Oracle.** A free `n`-nt tail at equilibrium must reproduce the WLC end-to-end distribution:
`⟨R_ee²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})]` with `L_p = 0.67 nm`, `L_c = n × 0.68 nm`.
**Met to ±15% across 3–28 nt.** ⚠️ But NOT the way this plan assumed: you cannot "simulate an isolated
16-nt tail and check ⟨R_ee²⟩ converges" — ⟨R_ee²⟩ is a long-wavelength mode and an MD run converges the
local angles long before it, then reports a confidently wrong answer with a *plateauing* tangent
correlation. Use `snupi_tails.pivot_sample_chain` (finding 3). What MD *can* validate cheaply is the
tail's **bond** equipartition, `½(EA/b)⟨Δb²⟩ = ½k_BT` — a fast local mode, and it still pins the bead
mass, the noise amplitude and fluctuation–dissipation over the new DOF. That is the fast test.

**Watch — resolved, measured.** `dt` did **not** collapse: the duplex core's stiffest mode (ω = 5251/ns)
already dominates the stiffest tail mode (ω = 1387/ns) by 3.8×, so VoltronCore's step is unchanged at
0.152 ps. 1 bead/nt stands; no coarser beads, no modified-GJF needed.

---

## SS-3 — hydrodynamic drag on the tails

**Built — see the ✅ SS-3 section at the top.** Everything the plan asked for landed (ss nodes blobbed
along each tail; short tails get their own single blob; σ_ss = 0.5 nm; the memory guard re-checked),
plus one thing it did not anticipate: **the tails were frozen rods, and no amount of correct drag would
have made them wave.** The initial conformation, not the friction, was what stood between SS-2 and a
tail that moves. That is now `snupi_tails._coil_run`.

The plan's one open question — *"pick a defensible ss value and document it"* — resolved better than
expected: the ss bead radius (0.5 nm) turned out to be needed **only in `D`**, so `C` could stay a
single-radius RPY and no unequal-radius (Zuk 2014) tensor was needed at all. See the SS-3 section for
why that is principled rather than lucky (the leading RPY term is radius-independent).

**Known-good reference.** k=8 blobs recover the hydrodynamic speedup (τ/τ_exact = 0.97); k<4 degenerates
to Stokes. Don't set k below 4. Still true, and untouched — the core partition is byte-identical with
tails plumbed in (pinned).

---
