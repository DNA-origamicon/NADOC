from __future__ import annotations

import pytest

from backend.core.mrdna_decoder import (
    _add_nucleotide_frames,
    mrdna_backbone_strain_profile,
    measure_mrdna_native_roundtrip,
    validate_decoded_frame,
)
from backend.core.mrdna_manifest import (
    MrdnaNucleotideIdentity,
    MrdnaNucleotideManifest,
    MrdnaNucleotideRecord,
    MrdnaRenderAddress,
)


def _manifest():
    identities = [MrdnaNucleotideIdentity(
        strand_id="s", segment_kind="domain", segment_id="0",
        nucleotide_ordinal=i,
    ) for i in range(3)]
    keys = [item.key() for item in identities]
    records = []
    for i, identity in enumerate(identities):
        records.append(MrdnaNucleotideRecord(
            identity=identity,
            render=MrdnaRenderAddress(helix_id="h", bp_index=i, direction="FORWARD"),
            strand_type="staple", classification="duplex",
            simulation_mode="interpolated", model_nucleotide_index=i,
            predecessor=keys[i - 1] if i else None,
            successor=keys[i + 1] if i + 1 < len(keys) else None,
        ))
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
            "helix_id": "h", "bp_index": i, "direction": "FORWARD", "copy": 0,
            "backbone_position": [i * 0.75, 0, 0],
            "simulation_mode": "interpolated", "classification": "duplex",
        }
        for i, record in enumerate(manifest.records)
    ]
    reference = [
        {"helix_id": "h", "bp_index": i, "direction": "FORWARD", "copy": 0,
         "backbone_position": [i * 0.5, 0, 0]}
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
            strand_id=strand, segment_kind="domain", segment_id="0",
            nucleotide_ordinal=bp,
        )
        for strand in ("f", "r") for bp in (0, 1)
    }
    records = []
    for strand, direction in (("f", "FORWARD"), ("r", "REVERSE")):
        for bp in (0, 1):
            identity = identities[(strand, bp)]
            records.append(MrdnaNucleotideRecord(
                identity=identity,
                render=MrdnaRenderAddress(helix_id="h", bp_index=bp, direction=direction),
                strand_type="staple", classification="duplex",
                simulation_mode="interpolated", model_nucleotide_index=len(records),
                predecessor=identities[(strand, 0)].key() if bp == 1 else None,
                successor=identities[(strand, 1)].key() if bp == 0 else None,
                pair=identities[("r" if strand == "f" else "f", bp)].key(),
            ))
    manifest = MrdnaNucleotideManifest(design_fingerprint="x", records=records)
    points = {}
    for record in records:
        sign = 1.0 if record.render.direction == "FORWARD" else -1.0
        # Rotate radial position by 90 degrees between bp: the strand path is
        # diagonal, while pair centers remain exactly on +Z.
        radial = [sign, 0, 0] if record.render.bp_index == 0 else [0, sign, 0]
        points[record.identity.key()] = {
            "identity": record.identity.key(), "helix_id": "h",
            "bp_index": record.render.bp_index, "direction": record.render.direction,
            "copy": 0, "backbone_position": [*radial[:2], float(record.render.bp_index)],
        }
    _add_nucleotide_frames(manifest, points)
    assert all(
        [point["tx"], point["ty"], point["tz"]] == pytest.approx([0, 0, 1])
        for point in points.values()
    )


def test_native_roundtrip_report_measures_full_pose_contract():
    reference = [{
        "helix_id": "h", "bp_index": 0, "direction": "FORWARD", "copy": 0,
        "backbone_position": [1, 2, 3], "base_normal": [1, 0, 0],
        "axis_tangent": [0, 0, 1],
    }]
    decoded = [{
        "helix_id": "h", "bp_index": 0, "direction": "FORWARD", "copy": 0,
        "backbone_position": [1, 2, 3], "nx": 1, "ny": 0, "nz": 0,
        "tx": 0, "ty": 0, "tz": 1,
    }]
    report = measure_mrdna_native_roundtrip(decoded, reference)
    assert report["n_matched"] == 1
    assert report["position_error_nm"]["max"] == pytest.approx(0)
    assert report["normal_error_deg"]["max"] == pytest.approx(0)
    assert report["tangent_error_deg"]["max"] == pytest.approx(0)
