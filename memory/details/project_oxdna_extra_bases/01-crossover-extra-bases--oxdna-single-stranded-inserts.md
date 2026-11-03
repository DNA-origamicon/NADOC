# Crossover extra bases → oxDNA (single-stranded inserts) — supporting detail

[Topic head](../../project_oxdna_extra_bases.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

# Crossover extra bases → oxDNA (single-stranded inserts)

`Crossover.extra_bases` (e.g. "TT" — single-stranded thymines that relieve junction
strain) are now materialized as real ssDNA nucleotides in the oxDNA topology +
configuration. Before this work they reached only the atomistic/GROMACS path
(`atomistic.py` `_build_extra_base_atoms`); the oxDNA writer ignored them, so a CG
relaxation of a design with extra bases was byte-identical to one without.

> **SIBLING FEATURE — read it if you touch the walk, the native seed, or any `__xb__` key
> filter:** [project_strand_extensions_sim](../../project_strand_extensions_sim.md). Strand
> extensions (5′/3′ ssDNA tails) now flow through the SAME `_walk_strand_nucleotides`,
> `topology_rows` and `resolved_nuc_map`. Two things there generalise a rule stated here:
> per-nucleotide sequence assignment keys off `step.base_override is not None` (NOT
> `is_extra_base` — extensions carry an override too), and a tail key is a 3-tuple whose
> `bp_index` is an ordinary `int >= 0`, so `isinstance(k[1], int)` filters written to catch
> `__xb__` do **not** catch it. Use `is_synthetic_nuc_key()`.

## What it does

All wiring is in `backend/physics/oxdna_interface.py`:

- `_walk_strand_nucleotides(design)` — the single source of truth for the
  strand→domain→bp nucleotide walk, shared by `_strand_nucleotide_order`,
  `topology_rows`, `count_undefined_bases`, `_strand_nucleotide_provenance`. Yields a
  `_NucStep` per emitted nucleotide INCLUDING extra-base inserts. Centralizing this
  was necessary because those consumers + the geometry resolver must agree on the
  particle order or anchors/positions silently shift.
- `crossover_extra_base_junctions(design)` — mirrors the atomistic `extra_base_xover_src`
  rule: an extra-base crossover inserts on the **owning strand** at the domain→domain
  transition (`prev.helix_id != next.helix_id and prev.end_bp == next.start_bp`).
  Keyed strand-scoped `(strand_id, prev_domain_index)`. Crossover-only (forced
  ligations out of scope). Base identity comes from the `extra_bases` chars, NOT from
  `strand.sequence` (which excludes them — so inserts do not consume `seq_idx`).
  **Owning-strand selection (reciprocal-crossover bug, fixed 2026-06-25):** register
  each crossover at ONLY its owning (src) half — the half sitting at a domain 3′ end,
  picked exactly like atomistic's `domain_end_to_strand` (half_a preferred when both
  halves are domain ends). Registering BOTH halves double-fired the strand walk on a
  *reciprocal* crossover (two strands swap helices at the SAME junction position →
  both strands match), so two strands emitted the SAME `(_XB_SENTINEL, xo_id, k)`
  insert key. That key collision corrupts `topology_rows`' `index_map`/threading:
  duplicate physical rows collapse to one index, the first occurrence is orphaned
  (`-1/-1` bonds, wrong strand id from last-write-wins), and the surviving n3/n5
  point cross-strand → oxDNA aborts at init with `Topology inconsistency detected:
  particle X's n3 points to Y, but that particle's n5 does not point back`.
  VoltronCore (TT on all 577 crossovers) had 3 reciprocal cases; 6hb/18hb had none
  (why earlier validation missed it). Pin:
  `test_reciprocal_crossover_owns_insert_on_one_strand` (can-go-red) +
  `test_all_crossovers_insert_keys_unique_and_topology_consistent`.
- Insert key = `("__xb__", crossover_id, k)` (`_XB_SENTINEL`), threaded in-chain so
  n3/n5 connect `prev_real → eb0 → … → next_real` automatically.
- `_resolve_extra_base_geometry` — position = lerp along the chord between the two
  flanking real nucleotides at `t=(k+1)/(n+1)`; a3 = chord (5′→3′), a1 ⟂ a3. Even
  spacing keeps backbone bonds ≈ chord/(n+1) (~0.66 nm), inside the FENE range.

Read-back (`read_configuration`, `read_configuration_full`,
`configuration_full_from_particles`) DROPS `__xb__` keys: inserts occupy a particle
slot (so real-nucleotide indices stay aligned) but are absent from the design-keyed
position map, so the CG `/display` route and `assert_relaxed_geometry_recovered` stay
keyed to real nucleotides. v1 limitation: extra bases are simulated but not rendered
in the relaxed CG view.
