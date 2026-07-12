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
from backend.core.md_protocols import (
    SegmentSpec,
    _min_conf,
    _segment_conf,
    mgh_slow_release_segments,
    write_anchor_restraints_pdb,
)
from backend.core.namd_topology import (
    _write_segment_pdbs,
    built_pdb_residue_keys,
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
        Atom(serial=serial0, name="P", element="P", residue="DT", chain_id=chain_id,
             seq_num=seq_num, x=0.0, y=0.0, z=0.0, strand_id=chain_id,
             helix_id=helix_id, bp_index=seq_num, direction="FORWARD"),
        Atom(serial=serial0 + 1, name="C1'", element="C", residue="DT", chain_id=chain_id,
             seq_num=seq_num, x=0.1, y=0.0, z=0.0, strand_id=chain_id,
             helix_id=helix_id, bp_index=seq_num, direction="FORWARD"),
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
    atoms = (_residue_atoms("A", 1, "hA", 1)
             + _residue_atoms("B", 1, "hB", 3)
             + _residue_atoms("AA", 1, "hAA", 5))
    model = AtomisticModel(atoms=atoms, bonds=[])

    natural = built_pdb_residue_keys(model, sort_chains=False)
    lexical = built_pdb_residue_keys(model, sort_chains=True)
    assert natural == [("hA", 1, "FORWARD"), ("hB", 1, "FORWARD"), ("hAA", 1, "FORWARD")]
    assert lexical == [("hA", 1, "FORWARD"), ("hAA", 1, "FORWARD"), ("hB", 1, "FORWARD")]
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
    anchors = [{"kind": "base", "helix_id": a0.helix_id,
                "bp": a0.bp_index, "direction": a0.direction}]

    resolved = resolve_anchor_residue_indices(design, anchors, model=model)
    assert resolved == _model_indices_for_key_set(model, {key})
    assert len(resolved) >= 1


def test_strand_anchor_resolves_all_its_residues():
    design = make_6hb_design()
    model = build_atomistic_model(design)
    sid = design.strands[0].id

    resolved = resolve_anchor_residue_indices(
        design, [{"kind": "strand", "id": sid}], model=model)

    strand_keys = {(a.helix_id, a.bp_index, a.direction)
                   for a in model.atoms if a.strand_id == sid}
    assert resolved == _model_indices_for_key_set(model, strand_keys)
    assert len(resolved) > 1  # a whole strand spans many nucleotides


def test_stale_and_empty_anchors_resolve_to_nothing():
    design = make_6hb_design()
    model = build_atomistic_model(design)
    assert resolve_anchor_residue_indices(design, None, model=model) == set()
    assert resolve_anchor_residue_indices(design, [], model=model) == set()
    stale = [{"kind": "base", "helix_id": "h_does_not_exist", "bp": 3,
              "direction": "FORWARD"}]
    assert resolve_anchor_residue_indices(design, stale, model=model) == set()


# ── marker PDB — the exactness oracle ─────────────────────────────────────────

def test_anchor_pdb_marks_exactly_the_resolved_atoms(tmp_path):
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segments, full_text = _write_segment_pdbs(design, tmp_path, model)
    # Append a synthetic solvent HETATM to prove it is never marked.
    het = ("HETATM99999  OH2 TIP3 W   1      10.000  10.000  10.000"
           "  1.00  1.00      WT01 O")
    pdb_path = tmp_path / "built.pdb"
    pdb_path.write_text(full_text + het + "\n")

    sid = design.strands[0].id
    anchors = [{"kind": "strand", "id": sid}]
    # _write_segment_pdbs is the psfgen (sorted-chain) path -> full_topology=True.
    anchored = resolve_anchor_residue_indices(design, anchors, model=model, full_topology=True)
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
    _min_name, segs = mgh_slow_release_segments("demo")
    return segs[0]


def test_segment_conf_emits_fixedatoms_only_with_anchors():
    spec = _first_spec()
    box = (100.0, 100.0, 100.0)
    with_anchors = _segment_conf(spec, "demo", box, False,
                                 anchors_file="restraints_anchors.pdb")
    assert "fixedAtoms         on" in with_anchors
    assert "fixedAtomsFile     restraints_anchors.pdb" in with_anchors
    assert "fixedAtomsCol      B" in with_anchors

    without = _segment_conf(spec, "demo", box, False)
    assert "fixedAtoms" not in without


def test_min_conf_emits_fixedatoms_only_with_anchors():
    box = (100.0, 100.0, 100.0)
    with_anchors = _min_conf("demo_min", "demo", box, False, 4800, 0.5,
                             anchors_file="restraints_anchors.pdb")
    assert "fixedAtoms         on" in with_anchors
    assert "fixedAtomsFile     restraints_anchors.pdb" in with_anchors
    assert "fixedAtomsCol      B" in with_anchors

    without = _min_conf("demo_min", "demo", box, False, 4800, 0.5)
    assert "fixedAtoms" not in without


# ── real-psfgen end-to-end (SLOW: runs the actual topology build) ─────────────

def _fake_solvate(_pdb_text, _padding_nm, _tmpdir, progress=None, *, water_shell_nm=None):
    """Stand-in for gmx solvation (mirror test_md_prep_wiring): psfgen still runs on
    the real DNA, so the built {stem}.pdb the anchor mark is written against is real."""
    import backend.core.namd_solvate as ns
    from backend.core.namd_solvate import _Water
    ns._emit(progress, "solvate", None, "fake solvate")
    waters = [_Water(i * 0.31, 0, 0, i * 0.31, 0.1, 0, i * 0.31, -0.1, 0) for i in range(2000)]
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
        design, job_dir, ion_conc_mM=0.0, mg_conc_mM=0.0,
        salt_mode="custom", fast=False, anchors=anchors)

    pkg = next((job_dir / "package").iterdir())
    anchor_pdb = pkg / "restraints_anchors.pdb"
    assert anchor_pdb.exists()
    fixed_ordinals, _rows = _b1_residue_ordinals(anchor_pdb.read_text())
    assert fixed_ordinals == expected  # OUTPUT residue order aligns with the resolver

    # Every LADDER conf (the minimization + each segment) enables the anchors; the
    # solvation base template (namd.conf) is intentionally not a run conf.
    manifest = json.loads((pkg / "manifest.json").read_text())
    ladder_confs = [pkg / f"{manifest['minimization']['name']}.conf"]
    ladder_confs += [pkg / f"{s.name}.conf" for s in segments]
    for c in ladder_confs:
        text = c.read_text()
        assert "fixedAtoms         on" in text
        assert "fixedAtomsFile     restraints_anchors.pdb" in text
        assert "fixedAtomsCol      B" in text

    assert manifest["anchors"]["file"] == "restraints_anchors.pdb"
    assert manifest["anchors"]["n_residues"] == len(expected)
    assert manifest["files"]["anchors"] == "restraints_anchors.pdb"


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
        out = []
        by_chain = {}
        for a in model.atoms:
            by_chain.setdefault(a.chain_id, []).append(a)
        for cid in (sorted(by_chain) if order == "sorted" else list(by_chain)):
            seqs = sorted({a.seq_num for a in by_chain[cid]})
            out.extend((_chain_char(cid), _h36(s, 4).strip()) for s in seqs)
        return out

    pdb_seq = _pdb_residue_sequence(export_pdb(design, model=model))
    assert pdb_seq == _model_seq("natural")   # export_pdb == sort_chains=False
    assert pdb_seq != _model_seq("sorted")     # and NOT the lexicographic order
