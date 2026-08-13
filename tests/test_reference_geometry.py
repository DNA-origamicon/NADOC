"""
Tests for the "reference geometry" feature.

A strand marked ``is_reference=True`` is an inactive backdrop: every generative
feature (bend/twist, sequence assignment, scaffold routing, autostaple) ignores
it, and it is excluded from exports/validation, while staying visible + editable.
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api import state as design_state
from backend.api.main import app
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.geometry import nucleotide_positions_arrays
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    ForcedLigation,
    HalfCrossover,
    Helix,
    OverhangConnection,
    OverhangSpec,
    Strand,
    StrandExtension,
    StrandType,
    Vec3,
)
from backend.core.sequences import assign_scaffold_sequence, assign_staple_sequences
from backend.core.validator import validate_design

client = TestClient(app)


def _bundle():
    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    return make_bundle_design(cells, length_bp=420)


# ── Model + persistence ────────────────────────────────────────────────────────


def test_is_reference_defaults_false_and_round_trips():
    s = Strand(
        domains=[
            Domain(helix_id="h", start_bp=0, end_bp=9, direction=Direction.FORWARD)
        ]
    )
    assert s.is_reference is False

    d = _bundle()
    d.strands[0].is_reference = True
    reloaded = Design.from_json(d.to_json())
    assert reloaded.strands[0].is_reference is True
    assert reloaded.strands[1].is_reference is False


def test_old_nadoc_without_field_loads_as_false():
    d = _bundle()
    data = d.model_dump(mode="json")
    for s in data["strands"]:
        s.pop("is_reference", None)  # simulate a pre-feature .nadoc file
    reloaded = Design.model_validate(data)
    assert all(s.is_reference is False for s in reloaded.strands)


def test_active_and_reference_helpers():
    d = _bundle()
    d.strands[0].is_reference = True
    assert d.reference_strands() == [d.strands[0]]
    assert d.strands[0] not in d.active_strands()
    assert len(d.active_strands()) == len(d.strands) - 1


def test_simulation_projection_removes_reference_strands_and_reference_only_helices():
    helices = [
        Helix(
            id=hid,
            axis_start=Vec3(x=x, y=0, z=0),
            axis_end=Vec3(x=x, y=0, z=3.4),
            length_bp=10,
        )
        for hid, x in (("active", 0.0), ("reference", 3.0))
    ]
    active = Strand(
        id="active-strand",
        domains=[
            Domain(
                helix_id="active", start_bp=0, end_bp=9, direction=Direction.FORWARD
            )
        ],
    )
    mixed_ref = Strand(
        id="mixed-reference-strand",
        is_reference=True,
        domains=[
            Domain(
                helix_id="active", start_bp=9, end_bp=0, direction=Direction.REVERSE
            )
        ],
    )
    reference_only = Strand(
        id="reference-only-strand",
        is_reference=True,
        domains=[
            Domain(
                helix_id="reference",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
            )
        ],
    )
    design = Design(helices=helices, strands=[active, mixed_ref, reference_only])

    simulation = design.without_reference_geometry()

    assert [s.id for s in simulation.strands] == [active.id]
    assert [h.id for h in simulation.helices] == ["active"]
    assert len(design.strands) == 3  # projection never mutates editor state

    from backend.physics.oxdna_interface import _strand_nucleotide_order

    assert len(_strand_nucleotide_order(simulation)) == 10


def test_simulation_projection_prunes_every_reference_owned_dependency():
    """The shared projection protects every engine from stale reference records."""
    design = Design(
        helices=[
            Helix(
                id="active", axis_start=Vec3(x=0, y=0, z=0),
                axis_end=Vec3(x=0, y=0, z=3.4), length_bp=10,
            ),
            Helix(
                id="reference", axis_start=Vec3(x=0, y=0, z=0),
                axis_end=Vec3(x=0, y=0, z=3.4), length_bp=10,
            ),
        ],
        strands=[
            Strand(
                id="active-strand",
                domains=[Domain(
                    helix_id="active", start_bp=0, end_bp=9,
                    direction=Direction.FORWARD,
                )],
            ),
            Strand(
                id="reference-strand",
                is_reference=True,
                domains=[Domain(
                    helix_id="reference", start_bp=0, end_bp=9,
                    direction=Direction.FORWARD,
                )],
            ),
        ],
        crossovers=[
            Crossover(
                id="active-xo",
                half_a=HalfCrossover(helix_id="active", index=5, strand=Direction.FORWARD),
                half_b=HalfCrossover(helix_id="active", index=5, strand=Direction.REVERSE),
            ),
            Crossover(
                id="reference-xo",
                half_a=HalfCrossover(helix_id="reference", index=5, strand=Direction.FORWARD),
                half_b=HalfCrossover(helix_id="active", index=5, strand=Direction.REVERSE),
            ),
        ],
        extensions=[
            StrandExtension(strand_id="active-strand", end="three_prime", sequence="T"),
            StrandExtension(strand_id="reference-strand", end="three_prime", sequence="T"),
        ],
        overhangs=[
            OverhangSpec(id="active-oh", helix_id="active", strand_id="active-strand"),
            OverhangSpec(id="reference-oh", helix_id="reference", strand_id="reference-strand"),
        ],
        overhang_connections=[
            OverhangConnection(
                overhang_a_id="active-oh", overhang_a_attach="root",
                overhang_b_id="active-oh", overhang_b_attach="free_end",
                linker_type="ss", length_value=1, length_unit="bp",
            ),
            OverhangConnection(
                overhang_a_id="active-oh", overhang_a_attach="root",
                overhang_b_id="reference-oh", overhang_b_attach="free_end",
                linker_type="ss", length_value=1, length_unit="bp",
            ),
        ],
        forced_ligations=[
            ForcedLigation(
                three_prime_helix_id="active", three_prime_bp=4,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id="active", five_prime_bp=5,
                five_prime_direction=Direction.FORWARD,
            ),
            ForcedLigation(
                three_prime_helix_id="reference", three_prime_bp=4,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id="active", five_prime_bp=5,
                five_prime_direction=Direction.FORWARD,
            ),
        ],
    )

    projected = design.without_reference_geometry()

    assert [h.id for h in projected.helices] == ["active"]
    assert [s.id for s in projected.strands] == ["active-strand"]
    assert [x.id for x in projected.crossovers] == ["active-xo"]
    assert [x.strand_id for x in projected.extensions] == ["active-strand"]
    assert [x.id for x in projected.overhangs] == ["active-oh"]
    assert len(projected.overhang_connections) == 1
    assert len(projected.forced_ligations) == 1


def test_namd_fast_size_estimate_cannot_count_reference_geometry():
    """Estimator-level defense protects every preview caller, even if it passes editor state."""
    from backend.core.md_vram import estimate_atoms_from_design_geometry

    design = _bundle()
    design.strands[0].is_reference = True
    projected = design.without_reference_geometry()

    assert estimate_atoms_from_design_geometry(design) == estimate_atoms_from_design_geometry(
        projected
    )


def test_simulation_preparer_snapshot_cannot_reintroduce_reference_geometry(tmp_path):
    """Engine-level defense applies even when a caller passes the editor design."""
    from backend.core.cando_runner import prepare_cando_job

    design = _bundle()
    reference = design.strands[0]
    design = design.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True})
            if s.id == reference.id
            else s
            for s in design.strands
        ]
    )

    class _Job:
        @staticmethod
        def job_dir(_workspace):
            return tmp_path / "job"

    prepare_cando_job(design, _Job(), tmp_path)
    snapshot = Design.model_validate_json((tmp_path / "job" / "design.json").read_text())

    assert all(not strand.is_reference for strand in snapshot.strands)
    assert reference.id not in {strand.id for strand in snapshot.strands}


# ── Sequence assignment skips reference strands ──────────────────────────────────


def test_assign_staple_sequences_preserves_reference_strand():
    d = _bundle()
    d, *_ = assign_scaffold_sequence(d, "M13mp18")
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    # Give the reference staple a deliberately wrong, frozen sequence.
    frozen_seq = "A" * sum(abs(dm.end_bp - dm.start_bp) + 1 for dm in staple.domains)
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True, "sequence": frozen_seq})
            if s.id == staple.id
            else s
            for s in d.strands
        ]
    )
    out = assign_staple_sequences(d)
    ref_out = next(s for s in out.strands if s.id == staple.id)
    assert ref_out.sequence == frozen_seq  # untouched
    # A different (active) staple did get a Watson-Crick complement.
    other = next(
        s
        for s in out.strands
        if s.strand_type == StrandType.STAPLE and not s.is_reference and s.sequence
    )
    assert set(other.sequence) <= set("ATGCN")


# ── Validation excludes reference strands ────────────────────────────────────────


def test_validator_excludes_reference_scaffold_from_count():
    d = _bundle()
    # Mark the only scaffold reference → validator reports "no scaffold".
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True}) if s.is_scaffold else s
            for s in d.strands
        ]
    )
    report = validate_design(d)
    msgs = [r.message for r in report.results]
    assert any("No scaffold strand defined." == m for m in msgs)


def test_validator_skips_reference_sequence_length_check():
    d = _bundle()
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    # A wrong-length sequence on a reference staple must NOT produce a failure.
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True, "sequence": "ACGT"})
            if s.id == staple.id
            else s
            for s in d.strands
        ]
    )
    report = validate_design(d)
    assert not any(staple.id in r.message and not r.passed for r in report.results)


# ── Deformation freeze ──────────────────────────────────────────────────────────


def test_reference_nucleotides_frozen_under_bend():
    d = _bundle()
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    helix_id = staple.domains[0].helix_id
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True}) if s.id == staple.id else s
            for s in d.strands
        ]
    )
    design_state.set_design(d)
    # Wide bend so the staple's nucleotides fall in the bent region.
    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 10,
            "plane_b_bp": 410,
            "params": {"curvature_deg_per_bp": 45.0 / 400, "direction_deg": 0.0},
            "cluster_ids": [],
        },
    )
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    helix = d.find_helix(helix_id)

    straight = nucleotide_positions_arrays(helix)
    deformed = deformed_nucleotide_arrays(helix, d)

    # mask = nucleotides belonging to the (reference) staple on this helix
    from backend.core.deformation import _reference_nuc_mask

    mask = _reference_nuc_mask(straight, helix, d)
    assert mask.any(), "reference staple should cover some nucleotides on its helix"

    # Without reference, the SAME nucleotides move under the bend.
    d_noref = d.copy_with(
        strands=[s.model_copy(update={"is_reference": False}) for s in d.strands]
    )
    deformed_noref = deformed_nucleotide_arrays(helix, d_noref)
    moved = ~np.isclose(deformed_noref["positions"], straight["positions"]).all(axis=1)
    assert (mask & moved).any(), (
        "bend should move some of the reference nucleotides when not frozen"
    )

    # With reference, those nucleotides keep their straight positions.
    np.testing.assert_allclose(
        deformed["positions"][mask],
        straight["positions"][mask],
        atol=1e-9,
    )


# ── PATCH /design/strands/reference route ────────────────────────────────────────


def test_patch_strands_reference_route_round_trips_with_geometry():
    d = _bundle()
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    design_state.set_design(d)
    r = client.patch(
        "/api/design/strands/reference",
        json={"strand_ids": [staple.id], "is_reference": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    out_strand = next(s for s in body["design"]["strands"] if s["id"] == staple.id)
    assert out_strand["is_reference"] is True
    # Route returns only affected-helix geometry (the freeze can move positions),
    # avoiding a full-design Voltron-scale recompute and JSON payload.
    assert body["partial_geometry"] is True
    assert body["changed_helix_ids"]
    assert body.get("nucleotides_compact"), "reference route must return geometry"
    assert body["feature_log_payloads_partial"] is True
    # Clearing it works too.
    r2 = client.patch(
        "/api/design/strands/reference",
        json={"strand_ids": [staple.id], "is_reference": False},
    )
    assert r2.status_code == 200, r2.text
    assert (
        next(s for s in r2.json()["design"]["strands"] if s["id"] == staple.id)[
            "is_reference"
        ]
        is False
    )


def test_patch_strands_reference_route_404_on_unknown_id():
    design_state.set_design(_bundle())
    r = client.patch(
        "/api/design/strands/reference",
        json={"strand_ids": ["does-not-exist"], "is_reference": True},
    )
    assert r.status_code == 404


# ── Export filtering ─────────────────────────────────────────────────────────────


# ── Clusters exclude reference geometry ──────────────────────────────────────────


def test_reference_helix_ids_only_when_all_strands_reference():
    sA = Strand(
        domains=[
            Domain(helix_id="h1", start_bp=0, end_bp=9, direction=Direction.FORWARD)
        ],
        is_reference=True,
    )
    sB = Strand(
        domains=[
            Domain(helix_id="h2", start_bp=0, end_bp=9, direction=Direction.FORWARD)
        ]
    )
    sC = Strand(
        domains=[
            Domain(helix_id="h2", start_bp=0, end_bp=9, direction=Direction.REVERSE)
        ],
        is_reference=True,
    )
    d = Design(strands=[sA, sB, sC])
    # h1: only reference → reference-only. h2: has active sB → NOT reference-only.
    assert d.reference_helix_ids() == {"h1"}


def _with_full_cluster(d):
    from backend.core.models import ClusterRigidTransform

    return d.copy_with(
        cluster_transforms=[
            ClusterRigidTransform(
                name="C1", is_default=True, helix_ids=[h.id for h in d.helices]
            )
        ]
    )


def test_marking_all_strands_reference_prunes_clusters():
    d = _with_full_cluster(_bundle())
    design_state.set_design(d)
    ids = [s.id for s in d.strands]
    r = client.patch(
        "/api/design/strands/reference", json={"strand_ids": ids, "is_reference": True}
    )
    assert r.status_code == 200, r.text
    for c in r.json()["design"]["cluster_transforms"]:
        assert c["helix_ids"] == [], (
            "every helix became reference-only → pruned from clusters"
        )


def test_partial_reference_keeps_shared_helices_in_clusters():
    d = _with_full_cluster(_bundle())
    design_state.set_design(d)
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    r = client.patch(
        "/api/design/strands/reference",
        json={"strand_ids": [staple.id], "is_reference": True},
    )
    assert r.status_code == 200, r.text
    # The scaffold still covers those helices → none is reference-only → cluster intact.
    assert r.json()["design"]["cluster_transforms"][0]["helix_ids"]


def test_reconcile_drops_reference_only_helices():
    from backend.core.cluster_reconcile import reconcile_cluster_membership

    before = _with_full_cluster(_bundle())
    after = before.copy_with(
        strands=[s.model_copy(update={"is_reference": True}) for s in before.strands]
    )
    out = reconcile_cluster_membership(before, after, None)
    assert out.cluster_transforms[0].helix_ids == []


def test_sequence_csv_export_omits_reference_strand():
    d = _bundle()
    d, *_ = assign_scaffold_sequence(d, "M13mp18")
    d = assign_staple_sequences(d)
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True}) if s.id == staple.id else s
            for s in d.strands
        ]
    )
    design_state.set_design(d)
    r = client.get("/api/design/export/sequence-csv")
    assert r.status_code == 200, r.text
    expected_rows = sum(
        1
        for s in d.strands
        if s.strand_type != StrandType.SCAFFOLD and not s.is_reference and s.domains
    )
    assert len(r.text.splitlines()) == expected_rows + 1


def test_sequence_csv_export_matches_cadnano_staple_format():
    d = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    design_state.set_design(d)

    r = client.get("/api/design/export/sequence-csv")
    assert r.status_code == 200, r.text

    lines = r.text.splitlines()
    assert lines[0] == "Start,End,Sequence,Length,Color"
    assert lines == [
        "Start,End,Sequence,Length,Color",
        f"0[41],0[0],{'?' * 42},42,#f7931e",
        f"1[0],1[41],{'?' * 42},42,#f7931e",
    ]


# ── Assembly view excludes reference geometry ────────────────────────────────────


def test_assembly_geometry_excludes_reference_strands():
    """A part placed in an assembly must NOT render its reference strands.

    The per-source design + nucleotides shipped by /assembly/geometry drop
    reference strands, while the persisted assembly source design keeps them
    (display-only filter — topology preserved).
    """
    assembly_state.close_session()
    d = _bundle()
    assert len(d.strands) >= 2
    ref = d.strands[0]
    d = d.copy_with(
        strands=[
            s.model_copy(update={"is_reference": True}) if s.id == ref.id else s
            for s in d.strands
        ]
    )

    client.post("/api/assembly")
    add = client.post(
        "/api/assembly/instances",
        json={"name": "Part", "source": {"type": "inline", "design": d.to_dict()}},
    )
    assert add.status_code == 201, add.text

    geo = client.get("/api/assembly/geometry").json()
    assert not geo["errors"], geo["errors"]
    src = next(iter(geo["sources"].values()))

    # Shipped design omits the reference strand.
    shipped_ids = {s["id"] for s in src["design"]["strands"]}
    assert ref.id not in shipped_ids
    assert len(shipped_ids) == len(d.strands) - 1

    # So do the nucleotides — nothing of the reference strand renders.
    sids: set = set()
    for helix_bucket in src["nucleotides_compact"].values():
        for dir_bucket in helix_bucket.values():
            sids.update(dir_bucket["sid"])
    assert ref.id not in sids
    assert sids, "active strands should still produce nucleotides"

    # Persisted assembly topology keeps the reference strand.
    persisted = assembly_state.get_or_404().instances[0].source.design
    assert any(s.is_reference for s in persisted.strands)
    assembly_state.close_session()
