"""
Tests for ``backend.core.assembly_flatten.flatten_assembly``.

The regression gate here is **zero dangling domain→helix references** after
flattening an assembly that carries a cross-part linker. Before the 2026-07 fix
the linker complement domains (addressed as ``"<inst_id>::<helix_id>"``) were
blindly ``asm::``-prefixed to ``"asm::<inst_id>::<helix_id>"`` — matching neither
the flattened part helix (``"inst-<inst_id>::<helix_id>"``) nor any real helix,
so the linker bridge silently connected to nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.assembly_flatten import flatten_assembly
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Assembly,
    AssemblyOverhangBinding,
    Design,
    Direction,
    Domain,
    Helix,
    Mat4x4,
    OverhangSpec,
    PartInstance,
    PartSourceFile,
    PartSourceInline,
    Strand,
    StrandType,
    Vec3,
)


def test_flatten_resolves_workspace_relative_file_source():
    """Current v2 .nass files store file sources relative to workspace/."""
    source = PartSourceFile(path="BigO.nadoc")
    asm = Assembly(instances=[PartInstance(id="bigo", name="BigO", source=source)])
    flat = flatten_assembly(asm)
    assert flat.helices
    assert flat.strands
    assert all(h.id.startswith("inst-bigo::") for h in flat.helices)


def test_flatten_keeps_the_user_facing_assembly_name():
    asm = Assembly(metadata={"name": "BigO-poly"})
    flat = flatten_assembly(asm)
    assert flat.id.startswith("flat_")
    assert flat.metadata.name == "BigO-poly"


def test_bigo_periodic_flatten_stitches_repeats_and_keeps_full_ssdna_ends():
    """BigO's 56 seam staples must bridge repeats, never jump across one copy.

    Three repeats have two physical junctions, hence 56*2 internal polymer staples.
    Each of the 56 strand families also has two open polymer ends; those terminal
    strands retain the source staple's full nucleotide count, with the absent
    neighbour half represented as a true terminal ssDNA extension.
    """
    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "BigO-poly.nass").read_text())
    part = Design.from_json((root / "workspace" / "BigO.nadoc").read_text())
    flat = flatten_assembly(assembly)

    periodic = [fl for fl in part.forced_ligations if fl.is_periodic_seam]
    internal = [s for s in flat.strands if s.id.startswith("polymer::")]
    terminal = [s for s in flat.strands if s.id.startswith("polymer-terminal::")]
    assert len(periodic) == 56
    assert len(internal) == len(periodic) * (len(assembly.instances) - 1)
    assert len(terminal) == len(periodic) * 2
    assert len(flat.forced_ligations) == len(internal)

    source_lengths = {
        sum(len(list(range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1))) for d in s.domains)
        for s in part.strands
        if any(
            d.end_bp == fl.three_prime_bp
            and d.helix_id == fl.three_prime_helix_id
            and i + 1 < len(s.domains)
            and s.domains[i + 1].start_bp == fl.five_prime_bp
            and s.domains[i + 1].helix_id == fl.five_prime_helix_id
            for fl in periodic
            for i, d in enumerate(s.domains)
        )
    }
    assert source_lengths
    extensions_by_strand = {ext.strand_id: ext for ext in flat.extensions}
    for strand in terminal:
        extension = extensions_by_strand[strand.id]
        assert (
            sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)
            + len(extension.sequence)
        ) in source_lengths
        assert extension.end in {"five_prime", "three_prime"}
        assert extension.label == "Polymer end"

    # Export walks the materialized strand objects directly: the 112 seam strands
    # therefore remain covalently threaded across their domain/instance boundary,
    # and the 112 terminal ssDNA halves contribute real particles.
    from backend.physics.oxdna_interface import topology_rows

    rows, n_strands = topology_rows(flat)
    assert n_strands == len(flat.strands) == 587
    assert len(rows) == 43120


def test_bigo_periodic_flatten_has_one_fem_component_and_registered_seams():
    """Scientific regression: all inter-repeat seam atoms remain co-located and
    every BigO repeat belongs to one mechanically connected CanDo mesh."""
    import numpy as np

    from backend.core.deformation import deformed_nucleotide_positions
    from backend.physics.fem_solver import _mesh_component_labels, build_fem_mesh

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "BigO-poly.nass").read_text())
    # Round-trip matches the job-registration boundary and derives ordinary
    # within-part crossover records from the stitched strand graph.
    flat = Design.from_json(flatten_assembly(assembly).to_json())
    positions = {
        (h.id, int(p["bp_index"]), p["direction"].value): np.asarray(
            p["backbone_position"], dtype=float
        )
        for h in flat.helices
        for p in deformed_nucleotide_positions(h, flat)
    }
    seam_distances = []
    for ligation in flat.forced_ligations:
        if not ligation.id.startswith("polymer-ligation::"):
            continue
        a = positions[(
            ligation.three_prime_helix_id, ligation.three_prime_bp,
            ligation.three_prime_direction.value,
        )]
        b = positions[(
            ligation.five_prime_helix_id, ligation.five_prime_bp,
            ligation.five_prime_direction.value,
        )]
        seam_distances.append(float(np.linalg.norm(a - b)))
    assert len(seam_distances) == 112
    assert max(seam_distances) < 0.8  # one normal backbone step (measured: 0.678 nm)

    mesh = build_fem_mesh(flat)
    n_components, _ = _mesh_component_labels(mesh)
    assert len(mesh.nodes) == 21168
    assert n_components == 1


def test_smallo_polymer_seams_are_normal_beams_not_rigid_links():
    """Each repeat boundary continues all six duplex axes by one ordinary bp step."""
    from backend.physics.fem_solver import FEM_RISE_PER_BP, build_fem_mesh

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "smallO-poly.nass").read_text())
    flat = Design.from_json(flatten_assembly(assembly).to_json())
    mesh = build_fem_mesh(flat)
    node_at = {(n.helix_id, n.global_bp): i for i, n in enumerate(mesh.nodes)}
    element_pairs = {
        frozenset((element.node_i, element.node_j)): element
        for element in mesh.elements
    }
    rigid_pairs = {
        frozenset((link.node_i, link.node_j)) for link in mesh.rigid_links
    }

    seams = [fl for fl in flat.forced_ligations if fl.id.startswith("polymer-ligation::")]
    assert len(seams) == 12  # six helices across two repeat boundaries
    for seam in seams:
        pair = frozenset((
            node_at[(seam.three_prime_helix_id, seam.three_prime_bp)],
            node_at[(seam.five_prime_helix_id, seam.five_prime_bp)],
        ))
        assert pair in element_pairs
        assert element_pairs[pair].length == pytest.approx(FEM_RISE_PER_BP)
        assert pair not in rigid_pairs


def test_smallo_polymer_fingerprint_is_stable_across_materialization():
    """Reloading an unchanged assembly must not mark its simulation jobs stale."""
    from backend.core.oxdna_staleness import oxdna_design_fingerprint

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "smallO-poly.nass").read_text())
    first = Design.from_json(flatten_assembly(assembly).to_json())
    second = Design.from_json(flatten_assembly(assembly).to_json())

    assert oxdna_design_fingerprint(first) == oxdna_design_fingerprint(second)
    assert [sd.id for o in first.overhangs for sd in o.sub_domains] == [
        sd.id for o in second.overhangs for sd in o.sub_domains
    ]


def test_smallo_polymer_ends_survive_oxdna_mrdna_and_cando_boundaries():
    """The two free ends of every polymerization-strand family are simulation sites.

    CanDo cannot equilibrate a free ssDNA coil, so its records are passive followers
    of the terminal duplex anchor; oxDNA/mrDNA model them as ordinary unpaired sites.
    """
    import numpy as np

    from backend.core.mrdna_manifest import build_mrdna_nucleotide_manifest
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    from backend.physics.fem_solver import build_fem_mesh, deformed_positions_with_axis
    from backend.physics.oxdna_interface import _strand_nucleotide_order, topology_rows

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "smallO-poly.nass").read_text())
    flat = Design.from_json(flatten_assembly(assembly).to_json())
    terminal_ids = {
        strand.id for strand in flat.strands if strand.id.startswith("polymer-terminal::")
    }
    assert len(terminal_ids) == 12

    # oxDNA/LAMMPS both consume this exact ordered particle topology.
    order = _strand_nucleotide_order(flat)
    rows, _ = topology_rows(flat)
    assert len(order) == len(rows) == 2394

    # mrDNA's identity manifest must retain the same total plus all 126 terminal
    # extension nucleotides (the remaining 126 terminal-strand nts are duplex).
    manifest = build_mrdna_nucleotide_manifest(
        flat, design_fingerprint=oxdna_design_fingerprint(flat)
    )
    assert len(manifest.records) == 2394
    terminal_records = [
        record for record in manifest.records if record.identity.strand_id in terminal_ids
    ]
    assert len(terminal_records) == 252
    assert sum(record.identity.segment_kind == "extension" for record in terminal_records) == 126

    # The CanDo/SNUPI display contract now also covers those 126 tail addresses.
    mesh = build_fem_mesh(flat)
    positions, _ = deformed_positions_with_axis(
        flat, mesh, np.zeros(6 * len(mesh.nodes), dtype=float)
    )
    assert len(positions) == 2394
    assert sum(row["helix_id"].startswith("__ext_") for row in positions) == 126


@pytest.mark.slow
def test_smallo_poly_namd_seed_has_no_ring_piercings():
    """Polymer ends use the reviewed terminal-extension atom placement.

    The former fake-helix representation produced eight permanent topological defects
    in this exact NAMD seed, including a 1.588 nm O3'-P bond through its own rings.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.ring_piercing import piercing_report

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "smallO-poly.nass").read_text())
    flat = Design.from_json(flatten_assembly(assembly).to_json())
    report = piercing_report(flat, model=build_atomistic_model(flat))
    assert report["n_pierced"] == 0, report["pierced"]


@pytest.mark.parametrize(
    "runner_module",
    [
        "backend.core.oxdna_runner",
        "backend.core.mrdna_runner",
        "backend.core.snupi_runner",
        "backend.core.blade_runner",
    ],
)
def test_every_engine_snapshot_loader_reconstructs_polymer_topology(
    tmp_path, runner_module,
):
    """Every worker must retain the derived crossovers CanDo previously lost."""
    import importlib

    root = Path(__file__).resolve().parents[1]
    assembly = Assembly.from_json((root / "workspace" / "smallO-poly.nass").read_text())
    flat = flatten_assembly(assembly)
    assert flat.crossovers == []  # derived at the persisted JSON boundary
    (tmp_path / "design.json").write_text(flat.model_dump_json())

    runner = importlib.import_module(runner_module)
    loaded = runner._load_snapshot_design(tmp_path)
    assert loaded is not None
    assert len(loaded.crossovers) == 78
    assert len(loaded.forced_ligations) == len(flat.forced_ligations) == 12


def test_flatten_rejects_missing_visible_file_source():
    asm = Assembly(instances=[PartInstance(
        id="missing", name="Missing", source=PartSourceFile(path="does-not-exist.nadoc"),
    )])
    with pytest.raises(FileNotFoundError, match="does-not-exist"):
        flatten_assembly(asm)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def _design_with_real_oh(oh_id: str, sequence: str | None) -> Design:
    length_bp = 8
    helix_id = f"hx_{oh_id}"
    strand_id = f"str_{oh_id}"
    helix = Helix(
        id=helix_id,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    direction = Direction.FORWARD if oh_id.endswith("_5p") else Direction.REVERSE
    strand = Strand(
        id=strand_id,
        domains=[
            Domain(
                helix_id=helix_id,
                start_bp=0,
                end_bp=length_bp - 1,
                direction=direction,
                overhang_id=oh_id,
            )
        ],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(
        id=oh_id,
        helix_id=helix_id,
        strand_id=strand_id,
        sequence=sequence,
        label=oh_id,
    )
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _seed_real_two_part_assembly() -> Assembly:
    d_a = _design_with_real_oh("oh-A_5p", "ACGTACGT")
    d_b = _design_with_real_oh("oh-B_3p", "GGGGCCCC")
    t_b = Mat4x4(values=[1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    a = Assembly(
        instances=[
            PartInstance(
                id="inst-A", name="PartA", source=PartSourceInline(design=d_a)
            ),
            PartInstance(
                id="inst-B",
                name="PartB",
                source=PartSourceInline(design=d_b),
                transform=t_b,
            ),
        ]
    )
    assembly_state.set_assembly(a)
    return a


def _conn_payload(
    *, linker_type="ds", attach_a="free_end", attach_b="root", length_value=8
):
    return {
        "instance_a_id": "inst-A",
        "overhang_a_id": "oh-A_5p",
        "overhang_a_attach": attach_a,
        "instance_b_id": "inst-B",
        "overhang_b_id": "oh-B_3p",
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": length_value,
        "length_unit": "bp",
    }


def _dangling_refs(design) -> list[tuple[str, str]]:
    """Every (strand_id, helix_id) domain reference with no matching helix."""
    helix_ids = {h.id for h in design.helices}
    return [
        (s.id, d.helix_id)
        for s in design.strands
        for d in s.domains
        if d.helix_id not in helix_ids
    ]


def test_flatten_empty_assembly_has_no_dangling_refs():
    _seed_real_two_part_assembly()
    flat = flatten_assembly(assembly_state.get_or_404())
    assert _dangling_refs(flat) == []


@pytest.mark.parametrize(
    "payload",
    [
        _conn_payload(linker_type="ds", attach_a="free_end", attach_b="root"),
        _conn_payload(linker_type="ss", attach_a="free_end", attach_b="free_end"),
        _conn_payload(
            linker_type="ss", attach_a="free_end", attach_b="free_end", length_value=0
        ),  # indirect (zero-length ss)
    ],
)
def test_flatten_linkered_assembly_has_no_dangling_refs(payload):
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections", json=payload)
    assert r.status_code == 200, r.text

    asm = assembly_state.get_or_404()
    # Precondition: the linker really did materialise complement strands.
    assert asm.assembly_strands, "linker produced no assembly strands"

    flat = flatten_assembly(asm)
    dangling = _dangling_refs(flat)
    assert dangling == [], f"linker complement domains dangle: {dangling}"

    # And the complement domain lands on the REAL flattened part helix.
    part_helix_ids = {h.id for h in flat.helices if h.id.startswith("inst-")}
    lnk_strands = [s for s in flat.strands if s.id.startswith("asm::__lnk__")]
    complement_refs = {
        d.helix_id
        for s in lnk_strands
        for d in s.domains
        if not d.helix_id.startswith("asm::__lnk__")  # exclude the bridge domain
    }
    assert complement_refs, "no complement domains found on the linker strands"
    assert complement_refs <= part_helix_ids, (
        f"complement domains not on a part helix: {complement_refs - part_helix_ids}"
    )


# ── Direct WC binding materialization (Phase D) ─────────────────────────────────


def _binding(assembly: Assembly) -> AssemblyOverhangBinding:
    sda = assembly.instances[0].source.design.overhangs[0].sub_domains[0].id
    sdb = assembly.instances[1].source.design.overhangs[0].sub_domains[0].id
    return AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="inst-A",
        sub_domain_a_id=sda,
        overhang_a_id="oh-A_5p",
        instance_b_id="inst-B",
        sub_domain_b_id=sdb,
        overhang_b_id="oh-B_3p",
    )


def test_flatten_materializes_direct_wc_binding_into_paired_topology():
    """A direct cross-part WC AssemblyOverhangBinding becomes a real duplex in the
    flattened Design: the driven overhang is relocated onto the driver's helix,
    antiparallel, over the same bp range."""
    a = _seed_real_two_part_assembly()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    assembly_state.set_assembly(a)

    flat = flatten_assembly(a)
    assert _dangling_refs(flat) == []

    # Find a helix hosting two domains covering the SAME bp range in OPPOSITE
    # directions — the materialized duplex.
    from collections import defaultdict

    by_helix = defaultdict(list)
    for s in flat.strands:
        for d in s.domains:
            by_helix[d.helix_id].append(d)

    def _covered(d):
        lo, hi = sorted((d.start_bp, d.end_bp))
        return frozenset(range(lo, hi + 1))

    paired = False
    for doms in by_helix.values():
        for i in range(len(doms)):
            for j in range(i + 1, len(doms)):
                di, dj = doms[i], doms[j]
                if _covered(di) == _covered(dj) and di.direction != dj.direction:
                    paired = True
    assert paired, "no antiparallel co-located domain pair (duplex) in flattened design"

    # The two overhangs must now sit on ONE helix (the driven relocated onto the
    # driver), not two.
    oh_helices = {d.helix_id for s in flat.strands for d in s.domains if d.overhang_id}
    assert len(oh_helices) == 1, f"overhangs not co-located: {oh_helices}"


def test_import_derives_duplexes_from_legacy_bindings():
    """Loading a .nass that carries legacy AssemblyOverhangBindings (and no
    duplexes) populates Assembly.duplexes on import."""
    a = _seed_real_two_part_assembly()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    assembly_state.close_session()

    r = client.post("/api/assembly/import", json={"content": a.to_json()})
    assert r.status_code == 200, r.text
    duplexes = r.json()["assembly"].get("duplexes", [])
    assert len(duplexes) == 1
    assert duplexes[0]["left"]["instance_id"] == "inst-A"
