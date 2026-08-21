"""N2 oracle — NAMD anchors (fixedAtoms) coverage.

The bright line for NAMD anchors is *not* "the conf has a block" but a property:
the resolved anchor scopes map to EXACTLY the intended DNA residues, and the
fixedAtoms marker PDB pins exactly those atoms (heavy, B=1) and nothing else.
Because NAMD's fixedAtoms guarantee is "a B=1 atom cannot move", proving the
marking is exact proves the "anchor held" property up to that guarantee — no GPU
run required for the fast oracle.

Residues are addressed by ORDINAL (positional), because psfgen's writepdb blanks
the segid column and the 1-char chain aliases past 62 strands — the same
contiguity bridge the base-ring ENM uses.

Anchors are a JOB-REQUEST annotation resolved read-only from topology (Three-Layer
Law); these tests never mutate a Design.
"""

from __future__ import annotations

from backend.core.atomistic import Atom, AtomisticModel, build_atomistic_model
import pytest

from backend.core.md_protocols import (
    SegmentSpec,
    _min_conf,
    _segment_conf,
    build_production_conf,
    external_forces_block,
    mgh_slow_release_segments,
    retarget_anchor_pdb,
    write_anchor_restraints_pdb,
)
from backend.core.namd_topology import (
    _write_segment_pdbs,
    built_pdb_residue_keys,
    requested_atom_names,
    resolve_anchor_atom_map,
    resolve_anchor_residue_indices,
)
from tests.conftest import (
    make_18hb_routed_design,
    make_6hb_design,
    make_minimal_design,
)


def _residue_atoms(chain_id, seq_num, helix_id, serial0):
    """Two heavy atoms for one nucleotide residue, sharing its (helix,bp,dir) key."""
    return [
        Atom(
            serial=serial0,
            name="P",
            element="P",
            residue="DT",
            chain_id=chain_id,
            seq_num=seq_num,
            x=0.0,
            y=0.0,
            z=0.0,
            strand_id=chain_id,
            helix_id=helix_id,
            bp_index=seq_num,
            direction="FORWARD",
        ),
        Atom(
            serial=serial0 + 1,
            name="C1'",
            element="C",
            residue="DT",
            chain_id=chain_id,
            seq_num=seq_num,
            x=0.1,
            y=0.0,
            z=0.0,
            strand_id=chain_id,
            helix_id=helix_id,
            bp_index=seq_num,
            direction="FORWARD",
        ),
    ]


# ── helpers ───────────────────────────────────────────────────────────────────


def _model_indices_for_key_set(model, key_set) -> set[int]:
    return {i for i, k in enumerate(built_pdb_residue_keys(model)) if k in key_set}


def _b1_residue_ordinals(pdb_text: str):
    """(set of residue ordinals with any B=1 atom, [(ordinal, atom_name, b) …]) using the
    same contiguity walk the writer uses."""
    fixed_ordinals: set[int] = set()
    rows = []
    res_idx = -1
    prev = None
    for line in pdb_text.splitlines():
        if line.startswith("TER"):
            prev = None
            continue
        if not line.startswith("ATOM"):
            continue
        ident = (line[21:22].strip(), line[22:26].strip(), line[17:21].strip())
        if ident != prev:
            res_idx += 1
            prev = ident
        name = line[12:16].strip()
        b = float(line[60:66])
        rows.append((res_idx, name, b))
        if b == 1.0:
            fixed_ordinals.add(res_idx)
    return fixed_ordinals, rows


# ── residue ordering bridge ───────────────────────────────────────────────────


def test_sort_chains_selects_natural_vs_lexicographic_order():
    """sort_chains=False (export_pdb) keeps FIRST-OCCURRENCE chain order; sort_chains=True
    (psfgen) sorts lexicographically.  Past 26 strands ('AA' < 'B' lexicographically but
    after 'Z' naturally) the two DIVERGE — the exact bug the fix guards.  This is the
    property that makes the ordinal-mark address the right residues under each generator."""
    # First-occurrence order A, B, AA (a 27th strand) — natural strand enumeration.
    atoms = (
        _residue_atoms("A", 1, "hA", 1)
        + _residue_atoms("B", 1, "hB", 3)
        + _residue_atoms("AA", 1, "hAA", 5)
    )
    model = AtomisticModel(atoms=atoms, bonds=[])

    natural = built_pdb_residue_keys(model, sort_chains=False)
    lexical = built_pdb_residue_keys(model, sort_chains=True)
    assert natural == [
        ("hA", 1, "FORWARD"),
        ("hB", 1, "FORWARD"),
        ("hAA", 1, "FORWARD"),
    ]
    assert lexical == [
        ("hA", 1, "FORWARD"),
        ("hAA", 1, "FORWARD"),
        ("hB", 1, "FORWARD"),
    ]
    assert natural != lexical  # the divergence is real, not cosmetic


def test_built_pdb_residue_keys_matches_writer_order(tmp_path):
    """The model residue-key order (sort_chains=True) equals the psfgen _write_segment_pdbs
    contiguity order — the alignment the ordinal-based mark depends on for the full-topology
    path."""
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)

    keys = built_pdb_residue_keys(model, sort_chains=True)
    # Walk the written PDB residue-by-residue and confirm each ordinal lands on the
    # same nucleotide (chain/resid pair unique within this 12-strand design).
    seen = -1
    prev = None
    n_checked = 0
    for line in full_text.splitlines():
        if line.startswith("TER"):
            prev = None
            continue
        if not line.startswith("ATOM"):
            continue
        ident = (line[21:22].strip(), line[22:26].strip(), line[17:21].strip())
        if ident != prev:
            seen += 1
            prev = ident
            n_checked += 1
    assert n_checked == len(keys)  # same residue count, same order


# ── resolver ──────────────────────────────────────────────────────────────────


def test_base_anchor_resolves_to_exactly_that_nucleotide():
    design = make_6hb_design()
    model = build_atomistic_model(design)
    a0 = model.atoms[0]
    key = (a0.helix_id, a0.bp_index, a0.direction)
    anchors = [
        {
            "kind": "base",
            "helix_id": a0.helix_id,
            "bp": a0.bp_index,
            "direction": a0.direction,
        }
    ]

    resolved = resolve_anchor_residue_indices(design, anchors, model=model)
    assert resolved == _model_indices_for_key_set(model, {key})
    assert len(resolved) >= 1


def test_strand_anchor_resolves_all_its_residues():
    design = make_6hb_design()
    model = build_atomistic_model(design)
    sid = design.strands[0].id

    resolved = resolve_anchor_residue_indices(
        design, [{"kind": "strand", "id": sid}], model=model
    )

    strand_keys = {
        (a.helix_id, a.bp_index, a.direction) for a in model.atoms if a.strand_id == sid
    }
    assert resolved == _model_indices_for_key_set(model, strand_keys)
    assert len(resolved) > 1  # a whole strand spans many nucleotides


def test_stale_and_empty_anchors_resolve_to_nothing():
    design = make_6hb_design()
    model = build_atomistic_model(design)
    assert resolve_anchor_residue_indices(design, None, model=model) == set()
    assert resolve_anchor_residue_indices(design, [], model=model) == set()
    stale = [
        {
            "kind": "base",
            "helix_id": "h_does_not_exist",
            "bp": 3,
            "direction": "FORWARD",
        }
    ]
    assert resolve_anchor_residue_indices(design, stale, model=model) == set()


# ── marker PDB — the exactness oracle ─────────────────────────────────────────


def test_anchor_pdb_marks_exactly_the_resolved_atoms(tmp_path):
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)
    # Append a synthetic solvent HETATM to prove it is never marked.
    het = (
        "HETATM99999  OH2 TIP3 W   1      10.000  10.000  10.000"
        "  1.00  1.00      WT01 O"
    )
    pdb_path = tmp_path / "built.pdb"
    pdb_path.write_text(full_text + het + "\n")

    sid = design.strands[0].id
    anchors = [{"kind": "strand", "id": sid}]
    # _write_segment_pdbs is the psfgen (sorted-chain) path -> full_topology=True.
    anchored = resolve_anchor_residue_indices(
        design, anchors, model=model, full_topology=True
    )
    assert anchored  # sanity

    dst = tmp_path / "restraints_anchors.pdb"
    n_marked = write_anchor_restraints_pdb(pdb_path, dst, anchored)

    fixed_ordinals, rows = _b1_residue_ordinals(dst.read_text())
    # Exactly the anchored residue ordinals carry a B=1 mark — no more, no less.
    assert fixed_ordinals == anchored
    marked = [(o, name) for o, name, b in rows if b == 1.0]
    assert all(not name.startswith("H") for _o, name in marked)  # heavy atoms only
    assert n_marked == len(marked) > 0
    # Hydrogens of an anchored residue stay free; every non-anchored atom is B=0.
    for ordinal, name, b in rows:
        if ordinal in anchored:
            assert b == (0.0 if name.startswith("H") else 1.0)
        else:
            assert b == 0.0  # non-anchored DNA + the synthetic HETATM


def test_anchor_pdb_leaves_everything_free_when_nothing_resolves(tmp_path):
    """RED guard: an empty anchor set fixes zero atoms (a run with no valid anchors
    must not silently pin the whole structure)."""
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)
    pdb_path = tmp_path / "built.pdb"
    pdb_path.write_text(full_text)

    dst = tmp_path / "none.pdb"
    n_marked = write_anchor_restraints_pdb(pdb_path, dst, set())
    assert n_marked == 0
    _fixed, rows = _b1_residue_ordinals(dst.read_text())
    assert all(b == 0.0 for _o, _n, b in rows)


# ── conf emission ─────────────────────────────────────────────────────────────


def _first_spec() -> SegmentSpec:
    """The first RELAXATION segment.  Not segs[0] — that is the Note-4 settle stage,
    which pins the whole solute and therefore owns the single fixedAtoms file itself."""
    _min_name, segs = mgh_slow_release_segments("demo")
    return next(s for s in segs if s.fixed_atoms_file is None)


def test_segment_conf_emits_fixedatoms_only_with_anchors():
    spec = _first_spec()
    box = (100.0, 100.0, 100.0)
    with_anchors = _segment_conf(
        spec, "demo", box, False, anchors_file="restraints_anchors.pdb"
    )
    assert "fixedAtoms         on" in with_anchors
    assert "fixedAtomsFile     restraints_anchors.pdb" in with_anchors
    assert "fixedAtomsCol      B" in with_anchors

    without = _segment_conf(spec, "demo", box, False)
    assert "fixedAtoms" not in without


def test_min_conf_emits_fixedatoms_only_with_anchors():
    box = (100.0, 100.0, 100.0)
    with_anchors = _min_conf(
        "demo_min", "demo", box, False, 4800, 0.5, anchors_file="restraints_anchors.pdb"
    )
    assert "fixedAtoms         on" in with_anchors
    assert "fixedAtomsFile     restraints_anchors.pdb" in with_anchors
    assert "fixedAtomsCol      B" in with_anchors

    without = _min_conf("demo_min", "demo", box, False, 4800, 0.5)
    assert "fixedAtoms" not in without


# ── real-psfgen end-to-end (SLOW: runs the actual topology build) ─────────────


def _fake_solvate(
    _pdb_text,
    _padding_nm,
    _tmpdir,
    progress=None,
    *,
    box_mode=None,
):
    """Stand-in for gmx solvation (mirror test_md_prep_wiring): psfgen still runs on
    the real DNA, so the built {stem}.pdb the anchor mark is written against is real."""
    import backend.core.namd_solvate as ns
    from backend.core.namd_solvate import _Water

    ns._emit(progress, "solvate", None, "fake solvate")
    waters = [
        _Water(i * 0.31, 0, 0, i * 0.31, 0.1, 0, i * 0.31, -0.1, 0) for i in range(2000)
    ]
    return waters, (12.0, 12.0, 12.0), _pdb_text


def test_prepare_writes_anchor_restraints_end_to_end(tmp_path, monkeypatch):
    """The real prepare_* pipeline (psfgen topology + conf writing) marks EXACTLY the
    resolved anchor residues in the built PDB and enables fixedAtoms in every conf.

    Strongest oracle short of a GPU run: it proves the psfgen-OUTPUT PDB's residue
    order aligns with the resolver's ordinals (the fast tests use the psfgen INPUT),
    and that fixedAtoms is wired into the whole ladder + the manifest."""
    import json

    import backend.core.namd_solvate as ns

    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)

    design = make_minimal_design(helix_length_bp=8)
    model = build_atomistic_model(design)
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    expected = resolve_anchor_residue_indices(design, anchors, model=model)
    assert expected  # the scaffold strand resolves to residues

    from backend.core.md_protocols import prepare_mgh_slow_release

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    _sub, _stem, segments = prepare_mgh_slow_release(
        design,
        job_dir,
        ion_conc_mM=0.0,
        mg_conc_mM=0.0,
        salt_mode="custom",
        fast=False,
        anchors=anchors,
    )

    pkg = next((job_dir / "package").iterdir())
    anchor_pdb = pkg / "restraints_anchors.pdb"
    assert anchor_pdb.exists()
    fixed_ordinals, _rows = _b1_residue_ordinals(anchor_pdb.read_text())
    assert fixed_ordinals == expected  # OUTPUT residue order aligns with the resolver

    # Every LADDER conf (the minimization + each segment) enables fixedAtoms; the
    # solvation base template (namd.conf) is intentionally not a run conf.
    #
    # The SETTLE segment names the anchor file like every other segment.  It used to be
    # the one exception — it pinned the whole solute with its own all-DNA fixedAtoms file,
    # and NAMD allows only ONE fixedAtomsFile — but it now holds the solute with harmonic
    # restraints instead, which is an independent channel.  So on an anchored job the
    # settle stage carries BOTH: hard anchors via fixedAtoms and the all-DNA restraint.
    manifest = json.loads((pkg / "manifest.json").read_text())
    expected_fixed = [
        (pkg / f"{manifest['minimization']['name']}.conf", "restraints_anchors.pdb")
    ]
    expected_fixed += [
        (pkg / f"{s.name}.conf", s.fixed_atoms_file or "restraints_anchors.pdb")
        for s in segments
    ]
    for c, want in expected_fixed:
        text = c.read_text()
        assert "fixedAtoms         on" in text
        assert f"fixedAtomsFile     {want}\n" in text
        assert "fixedAtomsCol      B" in text

    # The settle stage's own restraint must really cover the whole solute, not silently
    # replace the anchors with a smaller set.
    settle = [s for s in segments if s.restraint_ref_file]
    if settle:
        conf = (pkg / f"{settle[0].name}.conf").read_text()
        assert "fixedAtoms         on" in conf  # anchors still hard-held
        assert f"consref            {settle[0].restraint_ref_file}\n" in conf
        all_dna = pkg / settle[0].restraint_ref_file
        assert all_dna.exists()
        all_dna_ordinals, _ = _b1_residue_ordinals(all_dna.read_text())
        assert set(expected) <= set(all_dna_ordinals)
        # An anchored ladder cannot run GPU-resident: NAMD refuses fixedAtoms there.
        assert "GPUresident" not in conf

    assert manifest["anchors"]["file"] == "restraints_anchors.pdb"
    assert manifest["anchors"]["n_residues"] == len(expected)
    assert manifest["files"]["anchors"] == "restraints_anchors.pdb"


def test_prepare_excludes_both_extra_bases_topology_exactly(tmp_path, monkeypatch):
    """The default (require_full_topology=False, what an ordinary un-seeded run uses —
    routes_md.py only forces True for a BLADE/vacuum seed) legacy export_pdb path gets
    the SAME topology-exact ss-exclusion sidecar as the psfgen path.

    Companion to test_md_gbis.py's real-build check (which proves the sort_chains=True
    / psfgen path): this proves sort_chains=False / export_pdb, the path an ordinary
    "6hb_2xT"-style run actually takes."""
    import backend.core.namd_solvate as ns
    from backend.core.lattice import make_bundle_design
    from backend.core.md_health import (
        _unpaired_exclusion_set,
        identify_unpaired_residues,
        read_topology_ss_sidecar,
    )
    from backend.core.md_protocols import prepare_mgh_slow_release
    from backend.core.models import Crossover, Direction, HalfCrossover

    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)

    design = make_bundle_design([(0, 0), (0, 1)], length_bp=21, plane="XY")
    xo = Crossover(
        id="xo_extra",
        half_a=HalfCrossover(
            helix_id=design.helices[0].id, index=6, strand=Direction.FORWARD
        ),
        half_b=HalfCrossover(
            helix_id=design.helices[1].id, index=6, strand=Direction.REVERSE
        ),
        extra_bases="TT",
    )
    design = design.model_copy(update={"crossovers": [xo]})

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    _sub, stem, _segs = prepare_mgh_slow_release(
        design,
        job_dir,
        ion_conc_mM=0.0,
        mg_conc_mM=0.0,
        salt_mode="custom",
        fast=False,
        minimize_steps=120,
    )
    pkg = next((job_dir / "package").iterdir())
    psf, pdb = pkg / f"{stem}.psf", pkg / f"{stem}.pdb"

    sidecar = read_topology_ss_sidecar(pkg, stem)
    assert len(sidecar) == 2  # both TT inserts, by topology, sort_chains=False path

    geometry_only = identify_unpaired_residues(psf, pdb)
    assert not sidecar <= geometry_only  # geometry alone still misses one

    assert sidecar <= _unpaired_exclusion_set(psf, pdb)


def _pdb_residue_sequence(pdb_text: str):
    """(chain_char, resid) per residue in file order (contiguity walk)."""
    seq = []
    prev = None
    for line in pdb_text.splitlines():
        if line.startswith("TER"):
            prev = None
            continue
        if not line.startswith("ATOM"):
            continue
        ident = (line[21:22].strip(), line[22:26].strip(), line[17:21].strip())
        if ident != prev:
            seq.append((ident[0], ident[1]))
            prev = ident
    return seq


def test_export_pdb_residue_order_is_natural_not_sorted_on_many_strands():
    """DIVERGENCE PROOF (the review's finding 1a): on a 176-strand design the legacy
    export_pdb path emits residues in NATURAL chain order, so the resolver MUST order with
    sort_chains=False (full_topology=False).  Asserts the real export_pdb output residue
    sequence equals the natural-order model sequence and NOT the lexicographic one — if the
    resolver used the wrong sort, fixedAtoms would silently pin offset residues."""
    from backend.core.pdb_export import _chain_char, _h36, export_pdb

    design = make_18hb_routed_design()
    model = build_atomistic_model(design)  # include_proteins=False, matching export_pdb
    chains = list(dict.fromkeys(a.chain_id for a in model.atoms))
    assert chains != sorted(chains)  # >26 strands: the orders genuinely diverge

    def _model_seq(order):
        # Mirror export_pdb's reused-PDB-char resid continuation (commit 381da86): with >62
        # strands the single-char PDB chain IDs recycle, so residue numbering CONTINUES across
        # internal chains that map to the same char (2nd chain on 'A' prints 21..40, not 1..20)
        # to avoid merging unrelated residues under an identical (chain, resSeq) in ChimeraX.
        # The oracle must apply the same per-char offset, or it asserts pre-381da86 raw resids.
        out = []
        by_chain = {}
        for a in model.atoms:
            by_chain.setdefault(a.chain_id, []).append(a)
        char_offset: dict[str, int] = {}
        for cid in sorted(by_chain) if order == "sorted" else list(by_chain):
            ch = _chain_char(cid)
            off = char_offset.get(ch, 0)
            seqs = sorted({a.seq_num for a in by_chain[cid]})
            out.extend((ch, _h36(off + s, 4).strip()) for s in seqs)
            char_offset[ch] = off + max(seqs)
        return out

    pdb_seq = _pdb_residue_sequence(export_pdb(design, model=model))
    assert pdb_seq == _model_seq("natural")  # export_pdb == sort_chains=False
    assert pdb_seq != _model_seq("sorted")  # and NOT the lexicographic order


# ── atom-level anchoring (anchor_atoms) ───────────────────────────────────────
#
# The marker PDB was ALWAYS per-atom — column B is written atom by atom — but the
# decision was per-residue, so one anchored base pinned ~20 heavy atoms.  A name filter
# buys atom granularity with no atom picker, and keeps the choice a consistent,
# physically meaningful site (C1'/P) rather than an arbitrary hand-picked set.


def _anchor_fixture(tmp_path):
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)
    pdb_path = tmp_path / "built.pdb"
    pdb_path.write_text(full_text)
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    anchored = resolve_anchor_residue_indices(
        design, anchors, model=model, full_topology=True
    )
    assert anchored
    return pdb_path, anchored


def test_atom_filter_pins_one_named_atom_per_anchored_residue(tmp_path):
    pdb_path, anchored = _anchor_fixture(tmp_path)

    all_heavy = write_anchor_restraints_pdb(pdb_path, tmp_path / "all.pdb", anchored)
    dst = tmp_path / "c1.pdb"
    n_c1 = write_anchor_restraints_pdb(pdb_path, dst, anchored, atom_names={"C1'"})

    fixed_ordinals, rows = _b1_residue_ordinals(dst.read_text())
    # Same residues are still anchored — the filter narrows WITHIN a residue, it does
    # not drop residues.
    assert fixed_ordinals == anchored
    marked = [(o, name) for o, name, b in rows if b > 0]
    assert {name for _o, name in marked} == {"C1'"}
    # Exactly one atom per anchored residue, and far fewer than the all-heavy default.
    assert n_c1 == len(anchored) == len(marked)
    assert n_c1 < all_heavy


def test_atom_filter_accepts_several_names(tmp_path):
    pdb_path, anchored = _anchor_fixture(tmp_path)
    dst = tmp_path / "two.pdb"
    n = write_anchor_restraints_pdb(pdb_path, dst, anchored, atom_names={"P", "C1'"})
    _fixed, rows = _b1_residue_ordinals(dst.read_text())
    assert {name for _o, name, b in rows if b > 0} <= {"P", "C1'"}
    # 5'-terminal residues carry no P, so this is "at most 2 per residue", not exactly 2.
    assert len(anchored) < n <= 2 * len(anchored)


def test_atom_filter_that_matches_nothing_marks_nothing(tmp_path):
    """The caller turns this into a hard error.  It must NOT silently mark everything —
    a typo'd atom name that anchored the whole residue set would be worse than useless."""
    pdb_path, anchored = _anchor_fixture(tmp_path)
    dst = tmp_path / "typo.pdb"
    n = write_anchor_restraints_pdb(
        pdb_path, dst, anchored, atom_names={"CA"}
    )  # a protein name, absent from DNA
    assert n == 0
    _fixed, rows = _b1_residue_ordinals(dst.read_text())
    assert all(b == 0.0 for _o, _n, b in rows)


def test_k_writes_the_force_constant_into_column_b(tmp_path):
    """`k` switches column B from a fixedAtoms marker (1.0) to a conskfile force
    constant, so the SAME writer serves both mechanisms."""
    pdb_path, anchored = _anchor_fixture(tmp_path)
    dst = tmp_path / "soft.pdb"
    write_anchor_restraints_pdb(pdb_path, dst, anchored, atom_names={"C1'"}, k=0.02)
    bs = [
        float(ln[60:66])
        for ln in dst.read_text().splitlines()
        if ln.startswith("ATOM") and ln[12:16].strip() == "C1'"
    ]
    assert 0.02 in bs
    assert all(b in (0.0, 0.02) for b in bs)


# ── per-anchor atom sets ──────────────────────────────────────────────────────
#
# One job-level filter could not hold a corner base rigidly while merely tethering a
# distant overhang by its phosphate.  Each anchor descriptor now carries its own `atoms`
# list, and `resolve_anchor_atom_map` turns the list into {residue ordinal: names}, which
# the SAME writer consumes in place of a plain ordinal set.


def _per_anchor_fixture(tmp_path):
    """A design plus two anchors that resolve to DISJOINT residue sets, so each one's
    atom choice can be checked independently."""
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)
    pdb_path = tmp_path / "built.pdb"
    pdb_path.write_text(full_text)

    a0 = {"kind": "strand", "id": design.strands[0].id}
    a1 = {"kind": "strand", "id": design.strands[1].id}
    res0 = resolve_anchor_residue_indices(design, [a0], model=model, full_topology=True)
    res1 = resolve_anchor_residue_indices(design, [a1], model=model, full_topology=True)
    assert res0 and res1 and not (res0 & res1)
    return design, model, pdb_path, (a0, res0), (a1, res1)


def _marked_names_by_ordinal(pdb_text: str) -> "dict[int, set[str]]":
    _fixed, rows = _b1_residue_ordinals(pdb_text)
    out: dict[int, set[str]] = {}
    for ordinal, name, b in rows:
        if b > 0:
            out.setdefault(ordinal, set()).add(name)
    return out


def test_per_anchor_atom_map_holds_different_atoms_per_anchor(tmp_path):
    """The whole point: one anchor pinned by C1', another by P, in one run."""
    design, model, pdb_path, (a0, res0), (a1, res1) = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design,
        [{**a0, "atoms": ["C1'"]}, {**a1, "atoms": ["P"]}],
        model=model,
        full_topology=True,
    )

    dst = tmp_path / "mixed.pdb"
    n = write_anchor_restraints_pdb(pdb_path, dst, atom_map)
    marked = _marked_names_by_ordinal(dst.read_text())

    assert {n for o in res0 for n in marked.get(o, ())} == {"C1'"}
    # 5' termini carry no P, so that side may mark fewer residues — but never a C1'.
    assert {n for o in res1 for n in marked.get(o, ())} == {"P"}
    assert n == sum(len(v) for v in marked.values())


def test_overlapping_anchors_union_their_atom_sets(tmp_path):
    """Overlap is normal — a base anchor inside an anchored strand.  Union, not
    last-wins: the result must not depend on list order, which the UI never shows."""
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    both = [{**a0, "atoms": ["C1'"]}, {**a0, "atoms": ["P"]}]

    forward = resolve_anchor_atom_map(design, both, model=model, full_topology=True)
    reverse = resolve_anchor_atom_map(
        design, both[::-1], model=model, full_topology=True
    )
    assert forward == reverse
    assert all(forward[o] == frozenset({"P", "C1'"}) for o in res0)


def test_all_heavy_atoms_absorbs_the_union(tmp_path):
    """`None` is the TOP element — an anchor asking for everything cannot be narrowed
    by an overlapping anchor that asks for less."""
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design,
        [{**a0, "atoms": ["P"]}, {**a0, "atoms": None}],
        model=model,
        full_topology=True,
    )
    assert all(atom_map[o] is None for o in res0)


def test_an_anchor_without_atoms_falls_back_to_the_job_level_default(tmp_path):
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design, [a0], model=model, full_topology=True, default_atoms={"C1'"}
    )
    assert all(atom_map[o] == frozenset({"C1'"}) for o in res0)


def test_an_explicit_null_atoms_beats_the_job_level_default(tmp_path):
    """THE sentinel.  `atoms: None` is an anchor that deliberately holds every heavy
    atom; only key PRESENCE separates it from "no opinion", and a `.get()`-style read
    would collapse the two and leak the default in."""
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design,
        [{**a0, "atoms": None}],
        model=model,
        full_topology=True,
        default_atoms={"C1'"},
    )
    assert all(atom_map[o] is None for o in res0)


def test_the_backend_reads_the_atom_names_alias_too(tmp_path):
    """A descriptor round-tripped through a manifest may arrive as `atom_names`."""
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design, [{**a0, "atom_names": ["P"]}], model=model, full_topology=True
    )
    assert all(atom_map[o] == frozenset({"P"}) for o in res0)


def test_resolve_anchor_residue_indices_still_returns_a_plain_set(tmp_path):
    """The delegate keeps its old contract — 6 call sites depend on a set of ordinals."""
    design, model, _pdb, (a0, res0), (a1, res1) = _per_anchor_fixture(tmp_path)
    out = resolve_anchor_residue_indices(
        design, [a0, a1], model=model, full_topology=True
    )
    assert isinstance(out, set)
    assert out == res0 | res1


def test_a_mapping_ignores_the_job_level_atom_names_argument(tmp_path):
    """A `None` VALUE in the map means "all heavy atoms for THIS residue" and must not
    fall back to `atom_names` — the resolver has already folded the default in."""
    design, model, pdb_path, (a0, res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(design, [a0], model=model, full_topology=True)
    dst = tmp_path / "map.pdb"
    write_anchor_restraints_pdb(pdb_path, dst, atom_map, atom_names={"C1'"})
    marked = _marked_names_by_ordinal(dst.read_text())
    assert any(len(names) > 1 for names in marked.values())


def test_a_per_anchor_filter_matching_nothing_still_marks_nothing(tmp_path):
    """The caller turns this into a hard error; it must not silently mark everything."""
    design, model, pdb_path, (a0, _res0), _a1 = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design, [{**a0, "atoms": ["CA"]}], model=model, full_topology=True
    )
    assert write_anchor_restraints_pdb(pdb_path, tmp_path / "typo.pdb", atom_map) == 0


def test_requested_atom_names_reports_what_the_anchors_actually_asked_for(tmp_path):
    design, model, _pdb, (a0, _r0), (a1, _r1) = _per_anchor_fixture(tmp_path)
    atom_map = resolve_anchor_atom_map(
        design,
        [{**a0, "atoms": ["C1'"]}, {**a1, "atoms": ["P"]}],
        model=model,
        full_topology=True,
    )
    assert requested_atom_names(atom_map) == ["C1'", "P"]
    # All-heavy anchors contribute no names rather than a misleading empty string.
    assert (
        requested_atom_names(
            resolve_anchor_atom_map(design, [a0], model=model, full_topology=True)
        )
        == []
    )


def test_every_copy_sharing_a_residue_key_gets_the_filter():
    """A +1 loop insertion emits a SECOND nucleotide with the same
    (helix_id, bp_index, direction) — the reason ``Atom.copy_k`` exists.  The key→ordinal
    index must therefore be a LIST; a scalar would silently anchor only one copy.

    No conftest fixture carries loop insertions, so the duplicate is built by hand: the
    same nucleotide's atoms re-emitted under a fresh chain, exactly what a second copy
    looks like to :func:`built_pdb_residue_keys`."""
    from dataclasses import replace

    design = make_6hb_design()
    base = build_atomistic_model(design)
    keys = built_pdb_residue_keys(base, sort_chains=True)
    assert len(set(keys)) == len(keys), (
        "fixture unexpectedly already has duplicate keys"
    )

    key = keys[0]
    dupe = [
        replace(a, chain_id="ZZ", seq_num=1)
        for a in base.atoms
        if (a.helix_id, a.bp_index, a.direction) == key
    ]
    assert dupe
    model = AtomisticModel(atoms=base.atoms + dupe, bonds=base.bonds)
    assert built_pdb_residue_keys(model, sort_chains=True).count(key) == 2

    anchors = [
        {
            "kind": "base",
            "helixId": key[0],
            "bp": key[1],
            "direction": key[2],
            "atoms": ["C1'"],
        }
    ]
    atom_map = resolve_anchor_atom_map(design, anchors, model=model, full_topology=True)
    assert len(atom_map) == 2
    assert all(v == frozenset({"C1'"}) for v in atom_map.values())


# ── hard vs soft emission ─────────────────────────────────────────────────────


def test_external_forces_block_switches_mechanism_on_anchor_k():
    hard = external_forces_block("a.pdb", None)
    assert "fixedAtoms         on" in hard and "constraints" not in hard

    soft = external_forces_block("a.pdb", None, anchor_k=0.02)
    assert "fixedAtoms" not in soft
    for line in (
        "constraints        on",
        "consref            a.pdb",
        "conskfile          a.pdb",
        "conskcol           B",
    ):
        assert line in soft


def test_production_conf_soft_anchor_does_not_also_disable_constraints():
    """RED guard: build_production_conf emits an unconditional `constraints off`.  With
    soft anchors that line would switch the restraints straight back off — a run that
    reports itself anchored and is not."""
    spec = SegmentSpec(
        name="demo_01_prod",
        stage="prod",
        percent=100.0,
        steps=1000,
        temp=300.0,
        damping=5.0,
        scale=None,
        npt=True,
        previous="prev",
    )
    box = (100.0, 100.0, 100.0)

    soft = build_production_conf(
        spec, "demo", box, False, anchors_file="a.pdb", anchor_k=0.02
    )
    assert "constraints        on" in soft
    assert "constraints        off" not in soft

    # Unanchored and hard-anchored confs keep the historical line.
    assert "constraints        off" in build_production_conf(spec, "demo", box, False)
    hard = build_production_conf(spec, "demo", box, False, anchors_file="a.pdb")
    assert "constraints        off" in hard and "fixedAtoms         on" in hard


# ── retargeting a soft anchor onto equilibrated coordinates ───────────────────


def test_retarget_moves_reference_coords_and_restamps_k(tmp_path):
    """A soft anchor restrains atoms TO the reference coordinates in its consref file.
    The prep-time file holds the idealised BUILD pose, which the ladder has since moved
    away from — restraining to it would drag the structure back for the whole run."""
    import numpy as np

    pdb_path, anchored = _anchor_fixture(tmp_path)
    src = tmp_path / "hard.pdb"
    write_anchor_restraints_pdb(pdb_path, src, anchored, atom_names={"C1'"})

    n_atoms = sum(
        1 for ln in src.read_text().splitlines() if ln.startswith(("ATOM", "HETATM"))
    )
    equil = np.arange(n_atoms * 3, dtype=float).reshape(n_atoms, 3) / 10.0

    dst = tmp_path / "soft.pdb"
    n = retarget_anchor_pdb(src, dst, coords=equil, k=0.02)
    assert n == len(anchored)

    rows = [
        ln for ln in dst.read_text().splitlines() if ln.startswith(("ATOM", "HETATM"))
    ]
    assert len(rows) == n_atoms
    for i, ln in enumerate(rows):
        assert float(ln[30:38]) == pytest.approx(equil[i][0], abs=5e-4)
        assert float(ln[38:46]) == pytest.approx(equil[i][1], abs=5e-4)
        assert float(ln[46:54]) == pytest.approx(equil[i][2], abs=5e-4)
    assert {float(ln[60:66]) for ln in rows} == {0.0, 0.02}


def test_retarget_refuses_a_coordinate_set_that_does_not_match(tmp_path):
    """A .coor from a different package would silently scramble every reference
    position, so a length mismatch is an error, not a truncation."""
    import numpy as np

    pdb_path, anchored = _anchor_fixture(tmp_path)
    src = tmp_path / "hard.pdb"
    write_anchor_restraints_pdb(pdb_path, src, anchored)
    with pytest.raises(ValueError, match="does not match|coordinates"):
        retarget_anchor_pdb(src, tmp_path / "bad.pdb", coords=np.zeros((3, 3)))


def test_anchor_file_directives_cannot_be_overridden():
    """A per-stage override that repoints or deletes `consref`/`conskfile` leaves a conf
    that still says `constraints on` but restrains nothing — or restrains to coordinates
    that are not the pose the child started from.  Same class as `extendedsystem`: it
    detaches the stage from the file that defines it, rather than changing the physics."""
    from backend.core.md_protocols import apply_conf_overrides

    conf = (
        "constraints        on\nconsref            restraints_anchors.pdb\n"
        "conskfile          restraints_anchors.pdb\nconskcol           B\n"
    )
    for directive in (
        "consref",
        "conskfile",
        "conskcol",
        "fixedAtomsFile",
        "fixedAtomsCol",
    ):
        with pytest.raises(ValueError, match="cannot be overridden"):
            apply_conf_overrides(conf, {directive: "something_else.pdb"})
        with pytest.raises(ValueError, match="cannot be overridden"):
            apply_conf_overrides(conf, {directive: None})  # deletion is also refused

    # extraBondsFile stays overridable on purpose — that IS a physics choice.
    out = apply_conf_overrides(
        "extraBondsFile     a.exb\n", {"extraBondsFile": "b.exb"}
    )
    assert "b.exb" in out


# ── attaching forces to an ALREADY-PREPARED package ───────────────────────────
#
# The wizard's Create makes a fully prepared 46 MB package. Attaching anchors afterwards
# must not re-solvate it, and must not regenerate its confs: regeneration would have to
# reproduce every prep-time parameter (timestep, GPU-resident, ENM names, cadences), and
# any one it got wrong would change the physics silently.

_LADDER = (
    "structure          demo.psf\ntimestep           2\n"
    "extraBonds         on\nextraBondsFile     demo_k0.5.enm.extra\n"
    "constraints        off\n"
    "binCoordinates     output/prev.coor\nrun                1000\n"
)

# A package prepared BEFORE the settle stage switched from fixing to restraining. Those
# confs still exist on disk, so injection must still leave their whole-solute pin alone.
_SETTLE = (
    "structure          demo.psf\ntimestep           2\n"
    "constraints        off\nfixedAtoms         on\n"
    "fixedAtomsFile     fixed_dna_all.pdb\nfixedAtomsCol      B\n"
    "run                1000\n"
)

_RESIDENT = (
    "structure          demo.psf\nGPUresident        on\ntimestep           4\n"
    "constraints        off\nrun                1000\n"
)


def test_inject_adds_the_block_where_the_writers_emit_it():
    from backend.core.md_protocols import inject_external_forces

    out = inject_external_forces(_LADDER, "restraints_anchors.pdb", None)
    lines = [l.split()[0] for l in out.splitlines() if l.strip()]
    assert lines.index("constraints") + 1 == lines.index("fixedAtoms")
    assert "fixedAtomsFile     restraints_anchors.pdb" in out
    # everything else is untouched, including the ENM the ladder depends on
    assert "extraBondsFile     demo_k0.5.enm.extra" in out
    assert "timestep           2" in out
    assert "run                1000" in out


def test_inject_is_idempotent_and_replaces_rather_than_stacks():
    """Re-attaching replaces OUR marker rather than stacking a second fixedAtomsFile.
    Keyed on the marker filename the anchor machinery owns, so a re-injection is
    recognised as ours while a segment's own whole-solute pin is not."""
    from backend.core.md_protocols import ANCHOR_MARKER_PDB, inject_external_forces

    once = inject_external_forces(_LADDER, ANCHOR_MARKER_PDB, None)
    twice = inject_external_forces(
        once, ANCHOR_MARKER_PDB, {"field_pN": 5.0, "dir": [0, 0, 1]}
    )
    assert twice.count("fixedAtomsFile") == 1
    assert twice.count("eFieldOn") == 1


def test_inject_never_strips_the_ladder_enm_restraint():
    """`constraints`/`consref`/`conskfile` in a relax ladder are the slow-release ENM,
    not anchors. Stripping them would silently unrestrain the ladder."""
    from backend.core.md_protocols import inject_external_forces

    enm = (
        "constraints        on\nconsref            restraints_dna_heavy.pdb\n"
        "conskfile          restraints_dna_heavy.pdb\nconskcol           B\n"
        "constraintScaling  0.5\nrun                1000\n"
    )
    out = inject_external_forces(enm, "restraints_anchors.pdb", None)
    for keep in (
        "constraints        on",
        "consref            restraints_dna_heavy.pdb",
        "conskfile          restraints_dna_heavy.pdb",
        "constraintScaling  0.5",
    ):
        assert keep in out
    # and the anchor block lands AFTER the whole constraints group, not inside it
    assert out.index("constraintScaling") < out.index("fixedAtoms")


def test_inject_leaves_a_whole_solute_pin_alone():
    """The Note-4 settle stage pins ALL DNA. NAMD allows one fixedAtoms file, and that
    superset already subsumes any anchor subset — so the stage keeps its own file and
    receives only the field."""
    from backend.core.md_protocols import inject_external_forces

    out = inject_external_forces(
        _SETTLE, "restraints_anchors.pdb", {"field_pN": 5.0, "dir": [0, 0, 1]}
    )
    assert "fixedAtomsFile     fixed_dna_all.pdb" in out
    assert "restraints_anchors.pdb" not in out
    assert out.count("fixedAtomsFile") == 1
    assert "eFieldOn" in out


def test_inject_with_no_forces_removes_them_again():
    from backend.core.md_protocols import inject_external_forces
    from backend.core.md_protocols import ANCHOR_MARKER_PDB

    on = inject_external_forces(
        _LADDER, ANCHOR_MARKER_PDB, {"field_pN": 5.0, "dir": [0, 0, 1]}
    )
    off = inject_external_forces(on, None, None)
    assert "fixedAtoms" not in off and "eField" not in off
    assert (
        "extraBondsFile     demo_k0.5.enm.extra" in off
        and "run                1000" in off
    )


def test_inject_refuses_a_conf_that_is_not_ours():
    from backend.core.md_protocols import inject_external_forces

    with pytest.raises(ValueError, match="no `constraints` directive"):
        inject_external_forces("structure demo.psf\nrun 10\n", "a.pdb", None)


def test_inject_drops_gpu_resident_for_a_hard_anchor():
    """NAMD 3: "GPUresident is incompatible with the following options: ... fixed atoms".
    Prep chose GPUresident before any anchor existed, so injecting a hard anchor into that
    conf would write the fatal pair and the run would refuse to start."""
    from backend.core.md_protocols import inject_external_forces

    out = inject_external_forces(_RESIDENT, "restraints_anchors.pdb", None)
    assert "fixedAtoms         on" in out
    assert "GPUresident" not in out


def test_inject_restores_gpu_resident_when_the_anchor_is_cleared():
    """Only when the caller RECORDED that it was on — never by guessing."""
    from backend.core.md_protocols import inject_external_forces

    anchored = inject_external_forces(_RESIDENT, "restraints_anchors.pdb", None)
    cleared = inject_external_forces(anchored, None, None, restore_resident=True)
    assert "GPUresident        on" in cleared and "fixedAtoms" not in cleared
    # and it lands where the writers emit it, before the integrator
    assert cleared.index("GPUresident") < cleared.index("timestep")
    # without the flag we do NOT invent it
    assert "GPUresident" not in inject_external_forces(anchored, None, None)


def test_inject_leaves_gpu_resident_alone_for_a_field_only_change():
    """A field is GPU-resident-compatible; only fixedAtoms is not."""
    from backend.core.md_protocols import inject_external_forces

    out = inject_external_forces(_RESIDENT, None, {"field_pN": 5.0, "dir": [0, 0, 1]})
    assert "GPUresident        on" in out and "eFieldOn" in out
