from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.mrdna_manifest import (
    MrdnaNucleotideIdentity,
    MrdnaNucleotideManifest,
    MrdnaNucleotideRecord,
    MrdnaParticleBinding,
    MrdnaRenderAddress,
    bind_manifest_to_mrdna_particles,
    build_mrdna_nucleotide_manifest,
)


def _record(ordinal: int, *, predecessor=None, successor=None, pair=None):
    ident = MrdnaNucleotideIdentity(
        strand_id="s", segment_kind="domain", segment_id="0",
        nucleotide_ordinal=ordinal,
    )
    return MrdnaNucleotideRecord(
        identity=ident,
        render=MrdnaRenderAddress(
            helix_id="h", bp_index=ordinal, direction="FORWARD"
        ),
        strand_type="staple",
        classification="duplex",
        simulation_mode="direct",
        model_nucleotide_index=ordinal,
        particle_bindings=[MrdnaParticleBinding(particle_index=ordinal, particle_kind="DNA")],
        predecessor=predecessor,
        successor=successor,
        pair=pair,
    )


def test_manifest_round_trip_and_required_reader(tmp_path):
    a = _record(0, successor='["s","domain","0",1,0]')
    b = _record(1, predecessor='["s","domain","0",0,0]')
    manifest = MrdnaNucleotideManifest(design_fingerprint="v3:test", records=[a, b])
    path = manifest.write(tmp_path)
    assert path.name == "nucleotide_map.json"
    loaded = MrdnaNucleotideManifest.load_required(tmp_path)
    assert loaded == manifest
    assert loaded.records[0].render.key() == "h:0:FORWARD"


def test_manifest_rejects_duplicate_render_address():
    a = _record(0)
    b = _record(1).model_copy(update={"render": a.render})
    with pytest.raises(ValidationError, match="duplicate render address"):
        MrdnaNucleotideManifest(design_fingerprint="x", records=[a, b])


def test_manifest_rejects_missing_or_nonreciprocal_edges():
    with pytest.raises(ValidationError, match="missing successor"):
        MrdnaNucleotideManifest(
            design_fingerprint="x", records=[_record(0, successor="missing")]
        )
    with pytest.raises(ValidationError, match="non-reciprocal strand edge"):
        MrdnaNucleotideManifest(
            design_fingerprint="x",
            records=[
                _record(0, successor='["s","domain","0",1,0]'), _record(1)
            ],
        )


def test_manifest_requires_particle_for_direct_site_and_rejects_legacy_job(tmp_path):
    with pytest.raises(ValidationError, match="no particle binding"):
        MrdnaNucleotideRecord(
            identity=MrdnaNucleotideIdentity(
                strand_id="s", segment_kind="domain", segment_id="0",
                nucleotide_ordinal=0,
            ),
            render=MrdnaRenderAddress(helix_id="h", bp_index=0, direction="FORWARD"),
            strand_type="staple",
            classification="duplex",
            simulation_mode="direct",
            model_nucleotide_index=0,
        )
    with pytest.raises(RuntimeError, match="rerun the job"):
        MrdnaNucleotideManifest.load_required(tmp_path)


def test_builder_uses_exact_model_enumeration_for_domains_and_edges():
    from backend.core.models import Design, Direction, Domain, Helix, Strand, Vec3

    design = Design(
        helices=[Helix(
            id="h", axis_start=Vec3(x=0, y=0, z=0),
            axis_end=Vec3(x=0, y=0, z=2), length_bp=3,
        )],
        strands=[Strand(
            id="s", domains=[Domain(
                helix_id="h", start_bp=0, end_bp=2,
                direction=Direction.FORWARD,
            )],
        )],
    )
    manifest = build_mrdna_nucleotide_manifest(design, design_fingerprint="v3:x")
    assert [r.render.key() for r in manifest.records] == [
        "h:0:FORWARD", "h:1:FORWARD", "h:2:FORWARD",
    ]
    assert [r.model_nucleotide_index for r in manifest.records] == [0, 1, 2]
    assert manifest.records[0].successor == manifest.records[1].identity.key()
    assert manifest.records[1].predecessor == manifest.records[0].identity.key()


def test_instrumented_adapter_binds_source_indices_by_segment_contour():
    from backend.core.models import Design, Direction, Domain, Helix, Strand, Vec3
    from backend.parameterization.mrdna_inject import (
        CrossoverPotentialOverride,
        mrdna_model_from_nadoc_parameterized,
    )

    design = Design(
        helices=[Helix(
            id="h", axis_start=Vec3(x=0, y=0, z=0),
            axis_end=Vec3(x=0, y=0, z=3.34), length_bp=10,
        )],
        strands=[
            Strand(id="a", domains=[Domain(
                helix_id="h", start_bp=0, end_bp=9, direction=Direction.FORWARD,
            )]),
            Strand(id="b", domains=[Domain(
                helix_id="h", start_bp=9, end_bp=0, direction=Direction.REVERSE,
            )]),
        ],
    )
    model = mrdna_model_from_nadoc_parameterized(
        design, CrossoverPotentialOverride.from_database("T0")
    )
    manifest = build_mrdna_nucleotide_manifest(design, design_fingerprint="v3:x")
    bound = bind_manifest_to_mrdna_particles(manifest, model)
    assert all(record.particle_bindings for record in bound.records)
    assert all(record.simulation_mode == "interpolated" for record in bound.records)
    particle_ids = {p.idx for p in model.particles if p.name == "DNA"}
    assert {
        binding.particle_index
        for record in bound.records
        for binding in record.particle_bindings
    } <= particle_ids
    assert all(
        sum(binding.weight for binding in record.particle_bindings) == pytest.approx(1.0)
        for record in bound.records
    )

    # Fine's atomic tail clears CG beads before returning. NADOC rebuilds the exact
    # frozen-twist topology so particle ids bind to the final numbered CG PSF.
    from backend.core.mrdna_runner import _restore_final_binding_topology

    model.clear_beads()
    assert not any(segment.beads for segment in model.segments)
    _restore_final_binding_topology(model)
    fine_bound = bind_manifest_to_mrdna_particles(manifest, model)
    assert all(record.particle_bindings for record in fine_bound.records)
    assert all(record.simulation_mode == "direct" for record in fine_bound.records)
