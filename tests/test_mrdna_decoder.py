from __future__ import annotations

import pytest
import numpy as np
from types import SimpleNamespace

from backend.core.mrdna_decoder import (
    _add_nucleotide_frames,
    _mrdna_seed_particle_frames,
    _mrdna_orientation_to_backbone_frame,
    _mrdna_seed_reference_by_key,
    mrdna_backbone_strain_profile,
    measure_mrdna_native_roundtrip,
    validate_decoded_frame,
)
from backend.core.mrdna_manifest import (
    MrdnaNucleotideIdentity,
    MrdnaNucleotideManifest,
    MrdnaNucleotideRecord,
    MrdnaRenderAddress,
    MrdnaParticleBinding,
)
from backend.core.mrdna_bridge import (
    _MRDNA_REVERSE_PAIR_FRAME,
    _mrdna_nucleotide_orientation,
)


def _manifest():
    identities = [
        MrdnaNucleotideIdentity(
            strand_id="s",
            segment_kind="domain",
            segment_id="0",
            nucleotide_ordinal=i,
        )
        for i in range(3)
    ]
    keys = [item.key() for item in identities]
    records = []
    for i, identity in enumerate(identities):
        records.append(
            MrdnaNucleotideRecord(
                identity=identity,
                render=MrdnaRenderAddress(
                    helix_id="h", bp_index=i, direction="FORWARD"
                ),
                strand_type="staple",
                classification="duplex",
                simulation_mode="interpolated",
                model_nucleotide_index=i,
                predecessor=keys[i - 1] if i else None,
                successor=keys[i + 1] if i + 1 < len(keys) else None,
            )
        )
    return MrdnaNucleotideManifest(design_fingerprint="x", records=records)


def test_quality_reports_complete_good_frame():
    manifest = _manifest()
    points = {
        record.identity.key(): {"backbone_position": [i * 0.67, 0, 0]}
        for i, record in enumerate(manifest.records)
    }
    quality = validate_decoded_frame(manifest, points)
    assert quality["complete"] and quality["usable"]
    assert quality["max_bond_nm"] == pytest.approx(0.67)


def test_quality_rejects_missing_identity_and_design_spanning_bond():
    manifest = _manifest()
    keys = [record.identity.key() for record in manifest.records]
    points = {
        keys[0]: {"backbone_position": [0, 0, 0]},
        keys[1]: {"backbone_position": [30, 0, 0]},
    }
    quality = validate_decoded_frame(manifest, points)
    assert not quality["complete"] and not quality["usable"]
    assert quality["missing_identities"] == [keys[2]]
    assert quality["bond_errors"][0]["length_nm"] == pytest.approx(30)


def test_quality_keeps_transient_internal_axis_excursion_as_warning():
    manifest = _manifest()
    keys = [record.identity.key() for record in manifest.records]
    points = {
        keys[0]: {"backbone_position": [0, 0, 0]},
        keys[1]: {"backbone_position": [2.1, 0, 0]},
        keys[2]: {"backbone_position": [2.77, 0, 0]},
    }
    quality = validate_decoded_frame(manifest, points)
    assert quality["usable"]
    assert not quality["bond_errors"]
    assert quality["bond_warnings"][0]["junction"] is False


def test_quality_warns_for_axis_resolved_crossover_without_rejecting_frame():
    manifest = _manifest()
    second = manifest.records[1]
    # Make the first edge cross a segment boundary, as real staple crossovers do.
    moved_identity = second.identity.model_copy(update={"segment_id": "1"})
    old_key = second.identity.key()
    new_key = moved_identity.key()
    records = []
    for record in manifest.records:
        update = {}
        if record is second:
            update["identity"] = moved_identity
        if record.successor == old_key:
            update["successor"] = new_key
        if record.predecessor == old_key:
            update["predecessor"] = new_key
        records.append(record.model_copy(update=update))
    crossed = MrdnaNucleotideManifest(design_fingerprint="x", records=records)
    keys = [record.identity.key() for record in crossed.records]
    points = {
        keys[0]: {"backbone_position": [0, 0, 0]},
        keys[1]: {"backbone_position": [3.0, 0, 0]},
        keys[2]: {"backbone_position": [3.67, 0, 0]},
    }
    quality = validate_decoded_frame(crossed, points)
    assert quality["usable"]
    assert not quality["bond_errors"]
    assert quality["bond_warnings"][0]["junction"] is True


def test_backbone_strain_uses_manifest_edges_and_keeps_complete_frame():
    manifest = _manifest()
    positions = [
        {
            "identity": record.identity.key(),
            "helix_id": "h",
            "bp_index": i,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [i * 0.75, 0, 0],
            "simulation_mode": "interpolated",
            "classification": "duplex",
        }
        for i, record in enumerate(manifest.records)
    ]
    reference = [
        {
            "helix_id": "h",
            "bp_index": i,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [i * 0.5, 0, 0],
        }
        for i in range(3)
    ]
    result = mrdna_backbone_strain_profile(manifest, positions, reference)
    assert len(result["positions"]) == 3
    assert result["n_edges"] == 2
    assert all(p["strain"] == pytest.approx(0.5) for p in result["positions"])
    assert result["metric"] == "backbone_geometric"


def test_slab_tangent_follows_pair_centers_not_helical_backbone():
    """The slab long axis is the relaxed helix axis, not the winding strand path."""
    identities = {
        (strand, bp): MrdnaNucleotideIdentity(
            strand_id=strand,
            segment_kind="domain",
            segment_id="0",
            nucleotide_ordinal=bp,
        )
        for strand in ("f", "r")
        for bp in (0, 1)
    }
    records = []
    for strand, direction in (("f", "FORWARD"), ("r", "REVERSE")):
        for bp in (0, 1):
            identity = identities[(strand, bp)]
            records.append(
                MrdnaNucleotideRecord(
                    identity=identity,
                    render=MrdnaRenderAddress(
                        helix_id="h", bp_index=bp, direction=direction
                    ),
                    strand_type="staple",
                    classification="duplex",
                    simulation_mode="interpolated",
                    model_nucleotide_index=len(records),
                    predecessor=identities[(strand, 0)].key() if bp == 1 else None,
                    successor=identities[(strand, 1)].key() if bp == 0 else None,
                    pair=identities[("r" if strand == "f" else "f", bp)].key(),
                )
            )
    manifest = MrdnaNucleotideManifest(design_fingerprint="x", records=records)
    points = {}
    for record in records:
        sign = 1.0 if record.render.direction == "FORWARD" else -1.0
        # Rotate radial position by 90 degrees between bp: the strand path is
        # diagonal, while pair centers remain exactly on +Z.
        radial = [sign, 0, 0] if record.render.bp_index == 0 else [0, sign, 0]
        points[record.identity.key()] = {
            "identity": record.identity.key(),
            "helix_id": "h",
            "bp_index": record.render.bp_index,
            "direction": record.render.direction,
            "copy": 0,
            "backbone_position": [*radial[:2], float(record.render.bp_index)],
        }
    _add_nucleotide_frames(manifest, points)
    assert all(
        [point["tx"], point["ty"], point["tz"]] == pytest.approx([0, 0, 1])
        for point in points.values()
    )
    assert all(
        np.dot(
            np.asarray(point["base_position"]) - np.asarray(point["backbone_position"]),
            np.asarray([point["nx"], point["ny"], point["nz"]]),
        )
        == pytest.approx(0.3)
        for point in points.values()
    )


def test_native_roundtrip_report_measures_full_pose_contract():
    reference = [
        {
            "helix_id": "h",
            "bp_index": 0,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [1, 2, 3],
            "base_normal": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
        }
    ]
    decoded = [
        {
            "helix_id": "h",
            "bp_index": 0,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [1, 2, 3],
            "nx": 1,
            "ny": 0,
            "nz": 0,
            "tx": 0,
            "ty": 0,
            "tz": 1,
        }
    ]
    report = measure_mrdna_native_roundtrip(decoded, reference)
    assert report["n_matched"] == 1
    assert report["position_error_nm"]["max"] == pytest.approx(0)
    assert report["normal_error_deg"]["max"] == pytest.approx(0)
    assert report["tangent_error_deg"]["max"] == pytest.approx(0)


def test_decoder_uses_same_unbalanced_geometry_as_mrdna_seed(monkeypatch):
    """Crossover balancing must never be introduced only on read-back."""
    calls = []

    def fake_geometry(_design, _selection, *, junction_balance):
        calls.append(junction_balance)
        return [
            {
                "helix_id": "h",
                "bp_index": 2,
                "direction": "FORWARD",
                "copy": 0,
                "backbone_position": [1, 2, 3],
            }
        ]

    monkeypatch.setattr(
        "backend.core.design_geometry._geometry_for_helices", fake_geometry
    )
    result = _mrdna_seed_reference_by_key(object())
    assert calls == [False]
    assert result[("h", 2, "FORWARD", 0)]["backbone_position"] == [1, 2, 3]


def test_paired_orientation_frames_obey_mrdna_reader_contract():
    forward = SimpleNamespace(
        radial_hat=np.array([1.0, 0.0, 0.0]),
        axis_tangent=np.array([0.0, 0.0, 1.0]),
    )
    reverse = SimpleNamespace(
        radial_hat=np.array([-0.5, 0.5 * np.sqrt(3.0), 0.0]),
        axis_tangent=np.array([0.0, 0.0, 1.0]),
    )
    forward_frame = _mrdna_nucleotide_orientation(forward)
    reverse_frame = _mrdna_nucleotide_orientation(reverse, forward)
    # This is exactly the transform applied by
    # mrdna.readers.segmentmodel_from_lists.set_splines before its quaternion average.
    assert reverse_frame @ _MRDNA_REVERSE_PAIR_FRAME == pytest.approx(forward_frame)


def test_decoder_particle_frame_uses_authoritative_seed_not_restart_pdb(monkeypatch):
    identities = [
        MrdnaNucleotideIdentity(
            strand_id=name,
            segment_kind="domain",
            segment_id="0",
            nucleotide_ordinal=0,
        )
        for name in ("f", "r")
    ]
    keys = [identity.key() for identity in identities]
    records = [
        MrdnaNucleotideRecord(
            identity=identity,
            render=MrdnaRenderAddress(
                helix_id="h",
                bp_index=0,
                direction="FORWARD" if i == 0 else "REVERSE",
            ),
            strand_type="staple",
            classification="duplex",
            simulation_mode="direct",
            model_nucleotide_index=i,
            pair=keys[1 - i],
            particle_bindings=[
                MrdnaParticleBinding(
                    particle_index=4,
                    particle_kind="DNA",
                    weight=1.0,
                )
            ],
        )
        for i, identity in enumerate(identities)
    ]
    manifest = MrdnaNucleotideManifest(design_fingerprint="x", records=records)
    frame = np.eye(3)
    reverse = frame @ _MRDNA_REVERSE_PAIR_FRAME
    arrays = [None] * 5
    arrays[4] = np.asarray([frame, reverse])
    monkeypatch.setattr(
        "backend.core.mrdna_bridge._build_nt_arrays", lambda *_a, **_k: arrays
    )
    assert _mrdna_seed_particle_frames(manifest, object())[4] == pytest.approx(frame)


def test_mrdna_orientation_x_maps_to_documented_backbone_y_axis():
    frame = _mrdna_orientation_to_backbone_frame(
        np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])
    )
    assert frame is not None
    # mrDNA's DefaultOrientation Rz(+90°) maps nucleotide-backbone x onto
    # segment-frame +y. Expressed as an active reconstruction rotation, the
    # NADOC radial x axis therefore lands on +y when O points along +x.
    assert frame[:, 0] == pytest.approx([0.0, 1.0, 0.0])
    assert frame[:, 2] == pytest.approx([0.0, 0.0, 1.0])
