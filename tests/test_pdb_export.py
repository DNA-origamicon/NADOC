"""
Regression coverage for PDB/PSF export of NADOC's non-standard origami features.

The general-purpose PDB tests in ``test_atomistic.py`` all use a plain bundle with
none of the features below.  These exercise the three atom kinds the foundational
atomistic work added — crossover **extra bases**, strand **extensions** (5′/3′ tails),
and intra-helix **loop insertions** — and pin two things a viewer needs:

  * every such atom actually reaches the exported ATOM/PSF records, and
  * ATOM serials stay unique and consistent with the CONECT records (the mod-9999
    serial-wrap bug that silently corrupted connectivity for any design > 9999 atoms).
"""

import pytest

from backend.core.atomistic import (
    build_atomistic_model,
    atomistic_model_from_reference,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    AtomisticReference,
    AtomisticReferenceAtom,
    Crossover,
    Direction,
    Domain,
    HalfCrossover,
    LoopSkip,
    Strand,
    StrandExtension,
    StrandType,
)
from backend.core.pdb_export import (
    _h36,
    export_pdb,
    export_psf,
)
from backend.core.pdb_to_design import import_pdb
from backend.core.pdb_to_design import _decode_pdb_int


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _design_with_extra_bases_and_extension():
    """Two-helix strand: a crossover carrying "TT" extra bases + a 3′ "AAA" tail."""
    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=21, plane="XY")
    h0, h1 = base.helices[0].id, base.helices[1].id
    strand = Strand(
        id="xstrand",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id=h0, start_bp=0, end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id=h1, start_bp=10, end_bp=20, direction=Direction.FORWARD),
        ],
    )
    xo = Crossover(
        id="xo1",
        half_a=HalfCrossover(helix_id=h0, index=10, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h1, index=10, strand=Direction.FORWARD),
        extra_bases="TT",
    )
    ext = StrandExtension(id="ext1", strand_id="xstrand", end="three_prime", sequence="AAA")
    return base.model_copy(update={"strands": [strand], "crossovers": [xo], "extensions": [ext]})


def _design_with_loop_insertion():
    """Single helix with a +1 loop insertion at bp 10."""
    d = make_bundle_design(cells=[(0, 0)], length_bp=21, plane="XY")
    d.helices[0].loop_skips.append(LoopSkip(bp_index=10, delta=1))
    return d


def _atom_serial_fields(pdb: str):
    return [line[6:11].strip() for line in pdb.splitlines() if line.startswith("ATOM  ")]


def _conect_tokens(pdb: str):
    tokens = set()
    for line in pdb.splitlines():
        if not line.startswith("CONECT"):
            continue
        body = line[6:]
        for k in range(0, len(body), 5):
            tok = body[k:k + 5].strip()
            if tok:
                tokens.add(tok)
    return tokens


def test_pdb_can_store_residue_scalar_values_and_chimerax_recipe():
    design = _design_with_loop_insertion()
    model = build_atomistic_model(design)
    target = next(a for a in model.atoms if not a.copy_k)
    key = (target.helix_id, target.bp_index, str(getattr(target.direction, "value", target.direction)))
    pdb = export_pdb(
        design, model=model, scalar_by_key={key: 0.42},
        scalar_metadata={
            "title": "RMSF", "unit": "nm", "colormap": "viridis",
            "palette": "#000000:#ffffff", "lo": 0.1, "hi": 0.8,
        },
    )
    assert 'REMARK  NADOC_COLOR_VALUE RMSF (nm) stored in B-factor column.' in pdb
    assert 'color byattribute bfactor palette "#000000:#ffffff" range 0.1,0.8 target as' in pdb
    target_serials = {
        a.serial + 1 for a in model.atoms
        if (a.helix_id, a.bp_index, str(getattr(a.direction, "value", a.direction))) == key
    }
    target_lines = [line for line in pdb.splitlines() if line.startswith("ATOM  ") and _decode_pdb_int(line[6:11], 5) in target_serials]
    assert target_lines
    assert {float(line[60:66]) for line in target_lines} == {0.42}
    assert any(float(line[60:66]) == 0.0 for line in pdb.splitlines() if line.startswith("ATOM  "))


# ── Non-standard atoms reach the export ───────────────────────────────────────

def test_pdb_includes_extra_base_and_extension_atoms():
    design = _design_with_extra_bases_and_extension()
    model = build_atomistic_model(design)
    xb = [a for a in model.atoms if a.extra_base_k is not None]
    ext = [a for a in model.atoms if a.extension_id is not None]
    assert xb, "fixture produced no extra-base atoms"
    assert ext, "fixture produced no extension atoms"

    pdb = export_pdb(design)
    atom_lines = [l for l in pdb.splitlines() if l.startswith("ATOM  ")]
    # Every atom in the model — inserts and tails included — must be written.
    assert len(atom_lines) == len(model.atoms)


def test_viewer_pdb_emits_inserted_and_extension_residues_in_polymer_order():
    """ChimeraX infers false missing-structure links when ATOM order revisits a chain."""
    design = _design_with_extra_bases_and_extension()
    model = build_atomistic_model(design)
    assert any(
        a.seq_num > b.seq_num
        for a, b in zip(model.atoms, model.atoms[1:])
        if a.chain_id == b.chain_id
    )

    pdb = export_pdb(design, model=model, viewer_terminals=True)
    residue_order = []
    for line in pdb.splitlines():
        if not line.startswith("ATOM  "):
            continue
        key = (line[21], _decode_pdb_int(line[22:26], 4))
        if not residue_order or residue_order[-1] != key:
            residue_order.append(key)

    assert residue_order == sorted(residue_order, key=lambda key: (key[0], key[1]))
    assert len(residue_order) == len(set(residue_order))
    assert sum(line.startswith("TER") for line in pdb.splitlines()) == 1


def test_visualized_pdb_payload_applies_simulated_positions_to_both_extension_ends(monkeypatch):
    """Renderer ``__ext_`` beads must drive PDB atoms for both 5' and 3' tails."""
    import numpy as np
    from backend.api import routes_export_structure as routes

    design = _design_with_extra_bases_and_extension()
    five = StrandExtension(
        id="ext5", strand_id="xstrand", end="five_prime", sequence="T")
    design = design.model_copy(update={"extensions": [five, *design.extensions]})
    targets = {
        (five.id, 0): [80.0, 10.0, 5.0],
        ("ext1", 0): [90.0, 20.0, 5.0],
        ("ext1", 1): [91.0, 20.0, 5.0],
        ("ext1", 2): [92.0, 20.0, 5.0],
    }
    positions = [
        routes.PdbVisualizationPosition(
            helix_id=f"__ext_{ext_id}", bp_index=k, direction="FORWARD",
            backbone_position=xyz,
        )
        for (ext_id, k), xyz in targets.items()
    ]
    payload = routes.PdbVisualizationExport(positions=positions)
    monkeypatch.setattr(routes, "_design_for_export", lambda: design)

    response = routes.export_visualized_pdb_file(payload)
    pdb_by_serial = {
        _decode_pdb_int(line[6:11], 5) - 1: np.array([
            float(line[30:38]), float(line[38:46]), float(line[46:54])]) / 10.0
        for line in response.body.decode().splitlines()
        if line.startswith("ATOM  ")
    }
    _, _, ext_override = routes._pdb_visualization_overrides(positions)
    expected = build_atomistic_model(
        design, ext_pos_override=ext_override, close_backbone=True)

    for ext_id in (five.id, "ext1"):
        atoms = [a for a in expected.atoms if a.extension_id == ext_id and a.name == "C1'"]
        assert atoms
        for atom in atoms:
            assert np.allclose(pdb_by_serial[atom.serial], [atom.x, atom.y, atom.z], atol=6e-5)
            assert np.linalg.norm(pdb_by_serial[atom.serial] - targets[(ext_id, atom.ext_k)]) < 2.0


def test_pdb_includes_loop_insertion_atoms():
    design = _design_with_loop_insertion()
    model = build_atomistic_model(design)
    loop_atoms = [a for a in model.atoms if a.copy_k is not None]
    assert loop_atoms, "fixture produced no loop-insertion atoms"

    pdb = export_pdb(design)
    atom_lines = [l for l in pdb.splitlines() if l.startswith("ATOM  ")]
    assert len(atom_lines) == len(model.atoms)


def test_viewer_pdb_uses_chemically_valid_unphosphorylated_5prime_termini():
    design = make_bundle_design(cells=[(0, 0)], length_bp=12, plane="XY")
    pdb = export_pdb(design, viewer_terminals=True)
    lines = [line for line in pdb.splitlines() if line.startswith("ATOM  ")]

    by_residue: dict[tuple[str, int], set[str]] = {}
    for line in lines:
        by_residue.setdefault((line[21], int(line[22:26])), set()).add(line[12:16].strip())

    first_residues = [names for (chain, seq), names in by_residue.items() if seq == 1]
    assert first_residues
    for names in first_residues:
        assert "O5'" in names
        assert {"P", "OP1", "OP2"}.isdisjoint(names)

    # The next residue is internal and keeps its complete phosphodiester group.
    for names in (names for (chain, seq), names in by_residue.items() if seq == 2):
        assert {"P", "OP1", "OP2", "O5'"}.issubset(names)

    atom_serials = {line[6:11].strip() for line in lines}
    assert not (_conect_tokens(pdb) - atom_serials)


def test_export_import_roundtrip_preserves_coordinates_and_bond_endpoints():
    """NADOC's importer must treat a complete exported CONECT graph as authoritative.

    Re-inferring backbone connectivity from a heavily displaced structure can join
    residues at opposite ends; endpoint-coordinate signatures catch that even when
    the importer reorders atom serials.
    """
    design = make_bundle_design(cells=[(0, 0)], length_bp=12, plane="XY")
    design.strands[0].sequence = "A" * 12
    design.strands[1].sequence = "T" * 12
    source = build_atomistic_model(design)
    _imported_design, restored, _warnings = import_pdb(export_pdb(design))

    def atom_sig(atom):
        return (atom.name, round(atom.x, 4), round(atom.y, 4), round(atom.z, 4))

    def bond_sigs(model):
        by_serial = {a.serial: a for a in model.atoms}
        return {
            tuple(sorted((atom_sig(by_serial[i]), atom_sig(by_serial[j]))))
            for i, j in model.bonds
        }

    assert sorted(atom_sig(a) for a in restored.atoms) == sorted(atom_sig(a) for a in source.atoms)
    assert bond_sigs(restored) == bond_sigs(source)


def test_export_repairs_missing_consecutive_strand_backbone_bond():
    """A standard nucleotide may not become detached when model bonds are incomplete."""
    design = make_bundle_design(cells=[(0, 0)], length_bp=50, plane="XY")
    model = build_atomistic_model(design)
    by_key = {(a.chain_id, a.seq_num, a.name): a.serial for a in model.atoms}
    o3 = by_key[("A", 44, "O3'")]
    p = by_key[("A", 45, "P")]
    broken = model.__class__(
        atoms=model.atoms,
        bonds=[edge for edge in model.bonds if set(edge) != {o3, p}],
    )

    pdb = export_pdb(design, model=broken, viewer_terminals=True)
    conect = {
        tuple(sorted((parts[0], neighbor)))
        for line in pdb.splitlines()
        if line.startswith("CONECT")
        for parts in [[line[6:11].strip()]]
        for neighbor in [line[i:i + 5].strip() for i in range(11, len(line), 5)]
        if neighbor
    }

    assert tuple(sorted((_h36(o3 + 1, 5).strip(), _h36(p + 1, 5).strip()))) in conect
    assert "Restored 1 missing consecutive-strand O3'-P bonds" in pdb


def test_large_design_uses_only_serial_addressed_connectivity():
    """LINK cannot distinguish strands after one-character chain IDs wrap.

    ChimeraX otherwise resolves those records onto distant residues and draws a
    starburst of false bonds. Serial-addressed CONECT remains complete.
    """
    design = make_bundle_design(cells=[(i, 0) for i in range(32)], length_bp=4, plane="XY")
    model = build_atomistic_model(design)
    pdb = export_pdb(design, model=model, viewer_terminals=True)

    assert not any(line.startswith("LINK") for line in pdb.splitlines())
    exported_serials = {
        line[6:11].strip()
        for line in pdb.splitlines()
        if line.startswith("ATOM  ")
    }
    assert _conect_tokens(pdb) == exported_serials

    model_no = 0
    atom_ids_by_model: dict[int, list[tuple]] = {}
    for line in pdb.splitlines():
        if line.startswith("MODEL"):
            model_no = int(line.split()[1])
        elif line.startswith("ATOM  "):
            atom_ids_by_model.setdefault(model_no, []).append(
                (line[21], _decode_pdb_int(line[22:26], 4), line[12:16].strip()))
    assert len(atom_ids_by_model) == 2
    for atom_ids in atom_ids_by_model.values():
        assert len(atom_ids) == len(set(atom_ids)), (
            "each PDB submodel must have unique chain/residue/atom identifiers")
    assert sum(line.startswith("TER") for line in pdb.splitlines()) == len({a.chain_id for a in model.atoms})


# ── Serial integrity (the mod-9999 wrap regression) ───────────────────────────

def test_pdb_atom_serials_unique_and_match_conect():
    """ATOM serials must be unique and every CONECT token must reference one.

    A prior version wrapped serials mod-9999, so any design over 9999 atoms had
    non-unique ATOM serials that no longer matched the hybrid-36 CONECT records —
    broken connectivity in every viewer.
    """
    design = _design_with_extra_bases_and_extension()
    pdb = export_pdb(design)
    serials = _atom_serial_fields(pdb)
    assert len(serials) == len(set(serials)), "duplicate ATOM serials"
    dangling = _conect_tokens(pdb) - set(serials)
    assert not dangling, f"CONECT tokens with no matching ATOM serial: {sorted(dangling)[:8]}"


def test_pdb_serials_hybrid36_past_9999():
    """Above 9999 atoms the serial field stays 5 chars and stays unique (hybrid-36)."""
    # A design comfortably over the 9999 wrap point: 3 helices x 120 bp = 14400 atoms
    # (~44% past the wrap), which is all this pin needs — the assert below fails loudly
    # if the atom count per bp ever drops far enough to stop crossing it.
    design = make_bundle_design(cells=[(0, 0), (0, 1), (1, 0)], length_bp=120, plane="XY")
    model = build_atomistic_model(design)
    assert len(model.atoms) > 9999, "fixture not large enough to cross the wrap point"

    # Reuse the model just built: export_pdb() would otherwise run a second, identical
    # all-atom reconstruction of the same design.  Byte-identical output either way.
    pdb = export_pdb(design, model=model)
    serials = _atom_serial_fields(pdb)
    assert len(serials) == len(set(serials))
    dangling = _conect_tokens(pdb) - set(serials)
    assert not dangling
    # The atom just past the wrap should read "10000", not "1".
    assert "10000" in set(serials)


@pytest.mark.parametrize("value, encoded", [
    (99_999, "99999"),
    (100_000, "A0000"),
    (100_009, "A0009"),
    (100_010, "A000A"),
    (100_035, "A000Z"),
    (100_036, "A0010"),
])
def test_standard_hybrid36_serial_boundary(value, encoded):
    """ChimeraX and CONECT must agree immediately above the decimal PDB limit."""
    assert _h36(value, 5) == encoded
    assert _decode_pdb_int(encoded, 5) == value


# ── Backbone connectivity through inserts ─────────────────────────────────────

def test_extra_bases_chain_backbone_o3_to_p():
    """The strand backbone must run prev_real → eb0 → eb1 → next_real via O3'→P bonds."""
    design = _design_with_extra_bases_and_extension()
    model = build_atomistic_model(design)
    by_serial = {a.serial: a for a in model.atoms}

    # Collect the inter-residue O3'→P bonds that touch an extra base.
    touching = []
    for i, j in model.bonds:
        a, b = by_serial[i], by_serial[j]
        if {a.name, b.name} != {"O3'", "P"}:
            continue
        o3, p = (a, b) if a.name == "O3'" else (b, a)
        if o3.extra_base_k is not None or p.extra_base_k is not None:
            touching.append((o3, p))
    # 2 extra bases → 3 backbone links crossing them (in, between, out).
    assert len(touching) == 3


def test_extension_tail_bases_are_backbone_linked():
    """Each 3′ tail base carries a phosphate and links to its predecessor."""
    design = _design_with_extra_bases_and_extension()
    model = build_atomistic_model(design)
    by_serial = {a.serial: a for a in model.atoms}
    tail_seqs = sorted({a.seq_num for a in model.atoms if a.extension_id is not None})
    assert len(tail_seqs) == 3, "expected a 3-base (AAA) tail"

    # Every tail residue has a P atom (i.e. an incoming backbone phosphodiester).
    for seq in tail_seqs:
        names = {a.name for a in model.atoms if a.extension_id is not None and a.seq_num == seq}
        assert "P" in names

    # And there is an O3'→P bond feeding the first tail base from the anchor.
    linked = any(
        {by_serial[i].name, by_serial[j].name} == {"O3'", "P"}
        and (
            (by_serial[i].extension_id is None) != (by_serial[j].extension_id is None)
        )
        for i, j in model.bonds
    )
    assert linked, "no O3'→P bond bridging anchor to the first tail base"


# ── PSF carries the insert bonds ──────────────────────────────────────────────

def test_psf_nbond_count_matches_model_including_inserts():
    design = _design_with_extra_bases_and_extension()
    model = build_atomistic_model(design)
    psf = export_psf(design)
    nbond_line = next(l for l in psf.splitlines() if "!NBOND" in l)
    declared = int(nbond_line.split()[0])
    assert declared == len(model.bonds)


# ── Identity persistence round-trip (the dropped-field regression) ────────────

def test_atomistic_reference_roundtrip_preserves_insert_identity():
    """copy_k / extension_id / ext_k must survive AtomisticReference persistence.

    These fields were added by the foundational extra-base/extension/loop work but
    the reference schema and reconstruction never copied them, silently erasing
    tail/loop identity on the cached export path.
    """
    design = _design_with_extra_bases_and_extension()
    design.helices[0].loop_skips.append(LoopSkip(bp_index=5, delta=1))
    model = build_atomistic_model(design)

    from backend.core.atomistic import atomistic_reference_topology_hash

    ref_atoms = [
        AtomisticReferenceAtom(
            serial=a.serial, name=a.name, element=a.element, residue=a.residue,
            chain_id=a.chain_id, seq_num=a.seq_num, x=a.x, y=a.y, z=a.z,
            strand_id=a.strand_id, helix_id=a.helix_id, bp_index=a.bp_index,
            direction=a.direction, is_modified=a.is_modified,
            aux_helix_id=a.aux_helix_id, aux_t=a.aux_t,
            crossover_id=a.crossover_id, extra_base_k=a.extra_base_k,
            copy_k=a.copy_k, extension_id=a.extension_id, ext_k=a.ext_k,
        )
        for a in model.atoms
    ]
    design.atomistic_reference = AtomisticReference(
        topology_hash=atomistic_reference_topology_hash(design),
        atoms=ref_atoms,
        bonds=list(model.bonds),
    )
    # Serialize + reload to prove the pydantic schema keeps the fields.
    reloaded = design.__class__.model_validate_json(design.model_dump_json())
    rebuilt = atomistic_model_from_reference(reloaded)
    assert rebuilt is not None

    assert any(a.extension_id is not None for a in rebuilt.atoms), "extension_id lost"
    assert any(a.ext_k is not None for a in rebuilt.atoms), "ext_k lost"
    assert any(a.copy_k is not None for a in rebuilt.atoms), "copy_k lost"
    assert any(a.extra_base_k is not None for a in rebuilt.atoms), "extra_base_k lost"
