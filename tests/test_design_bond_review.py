"""Read-only review counts realized bonds and detects the historical import failure.

External source fixtures are imported only in memory. No test publishes a
structure or substitutes diagnostic metadata for construction history.
"""

import gzip
import json
from pathlib import Path

import pytest

from backend.core import design_bond_review as review
from backend.core.cadnano import import_cadnano
from backend.core.models import ForcedLigation
from tests.test_cadnano_honeycomb_grid import source as translated_source


GUR = Path(__file__).parent / "fixtures" / "cadnano_gur_2016_6hb.json.gz"


class _ForcedRecordView:
    """Diagnostic annotation input over an unchanged imported design."""

    def __init__(self, design, records):
        self._design = design
        self.forced_ligations = records

    def __getattr__(self, name):
        return getattr(self._design, name)


@pytest.fixture(scope="module")
def gur_source():
    return json.loads(gzip.decompress(GUR.read_bytes()))


def source_bond_counts(data):
    """Count explicit source next pointers independently of imported domains."""
    all_bonds = interhelix_bonds = 0
    for track in data["vstrands"]:
        assert not any(track["loop"]) and not any(track["skip"])
        for kind in ("scaf", "stap"):
            for _previous_num, _previous_bp, next_num, _next_bp in track[kind]:
                if next_num != -1:
                    all_bonds += 1
                    interhelix_bonds += next_num != track["num"]
    return all_bonds, interhelix_bonds


@pytest.mark.parametrize("count,total,expected", [
    (0, 0, False), (0, 5, False), (1, 5, False), (2, 10, False),
    (1, 4, True), (3, 10, True), (20, 100, False), (21, 100, True),
])
def test_threshold_is_strictly_greater_than_twenty_percent(count, total, expected):
    assert review._exceeds_threshold(count, total) is expected


@pytest.mark.parametrize("importer_version", [1, 3])
def test_real_source_bond_counts_and_junction_trigger(gur_source, importer_version):
    design, _ = import_cadnano(gur_source, importer_version=importer_version)
    before = design.model_dump_json()
    result = review.review_design_bonds(design, include_geometry=False)
    all_bonds, interhelix_bonds = source_bond_counts(gur_source)
    counts = result["counts"]
    assert counts["backbone_bonds"] == all_bonds
    assert counts["interhelix_bonds"] == interhelix_bonds
    assert counts["matched_forced_bonds"] == len(design.forced_ligations)
    assert counts["unmatched_forced_records"] == 0
    if importer_version == 1:
        assert result["review_required"]
        assert result["ratios"]["forced_interhelix"] > 0.2
        assert "FORCED_JUNCTION_FRACTION_GT_20_PERCENT" in result["reason_codes"]
    else:
        assert result["ratios"]["forced_interhelix"] < 0.2
        assert result["review_required"] is False
    assert design.model_dump_json() == before
    assert review.review_design_bonds(design, include_geometry=False) == result


def test_pending_forced_record_does_not_create_a_bond_or_inflate_the_fraction():
    design, _ = import_cadnano(translated_source(), importer_version=3)
    scaffold = [s for s in design.strands if s.is_scaffold]
    end, start = scaffold[0].domains[-1], scaffold[1].domains[0]
    pending = ForcedLigation(
        three_prime_helix_id=end.helix_id, three_prime_bp=end.end_bp,
        three_prime_direction=end.direction,
        five_prime_helix_id=start.helix_id, five_prime_bp=start.start_bp,
        five_prime_direction=start.direction)
    assert not design.forced_ligations
    baseline = review.review_design_bonds(design, include_geometry=False)
    candidate = _ForcedRecordView(design, [pending])
    result = review.review_design_bonds(candidate, include_geometry=False)
    for key in ("backbone_bonds", "interhelix_bonds", "matched_forced_bonds",
                "matched_forced_interhelix_bonds"):
        assert result["counts"][key] == baseline["counts"][key]
    assert result["counts"]["unmatched_forced_records"] == 1
    assert result["ratios"] == baseline["ratios"]
    assert result["review_required"] is False


def test_duplicate_forced_annotations_do_not_double_count_the_real_bond():
    design, _ = import_cadnano(translated_source(), importer_version=1)
    forced, = design.forced_ligations
    candidate = _ForcedRecordView(design, [forced,
        forced.model_copy(update={"id": "duplicate-diagnostic-record"})])
    result = review.review_design_bonds(candidate, include_geometry=False)
    assert result["counts"]["matched_forced_bonds"] == 1
    assert result["counts"]["matched_forced_interhelix_bonds"] == 1
    assert result["ratios"]["forced_interhelix"] == 1


def test_topology_only_review_never_requests_geometry_or_claims_it_is_complete(monkeypatch):
    design, _ = import_cadnano(translated_source(), importer_version=3)
    monkeypatch.setattr(review, "_geometry_for_design",
                        lambda *_args, **_kwargs: pytest.fail("Geometry was requested"))
    result = review.review_design_bonds(design, include_geometry=False)
    assert result["geometry"]["requested"] is False
    assert result["geometry"]["status"] == "not_checked"
    assert "BOND_GEOMETRY_INCOMPLETE" not in result["reason_codes"]


def test_requested_missing_geometry_requires_review_instead_of_passing(monkeypatch):
    design, _ = import_cadnano(translated_source(), importer_version=3)
    monkeypatch.setattr(review, "_geometry_for_design", lambda *_args, **_kwargs: [])
    before = design.model_dump_json()
    result = review.review_design_bonds(design)
    geometry = result["geometry"]
    assert result["review_required"]
    assert "BOND_GEOMETRY_INCOMPLETE" in result["reason_codes"]
    assert geometry["requested"] and not geometry["complete"]
    assert geometry["status"] == "incomplete"
    assert geometry["measured_bonds"] == 0
    assert geometry["missing_bonds"] == result["counts"]["backbone_bonds"]
    assert design.model_dump_json() == before


def test_native_import_geometry_avoids_the_legacy_stretched_junction_trigger(gur_source):
    old, _ = import_cadnano(gur_source, importer_version=1)
    native, _ = import_cadnano(gur_source, importer_version=3)
    old_result = review.review_design_bonds(old)
    before = native.model_dump_json()
    native_result = review.review_design_bonds(native)
    assert old_result["geometry"]["complete"] and native_result["geometry"]["complete"]
    assert old_result["geometry"]["threshold_nm"] == 1.2
    assert native_result["geometry"]["threshold_nm"] == 1.2
    assert old_result["geometry"]["fraction_interhelix"] > 0.2
    assert "LONG_JUNCTION_FRACTION_GT_20_PERCENT" in old_result["reason_codes"]
    assert native_result["geometry"]["fraction_interhelix"] < 0.2
    assert "LONG_JUNCTION_FRACTION_GT_20_PERCENT" not in native_result["reason_codes"]
    assert native_result["geometry"]["long_interhelix"] < old_result["geometry"]["long_interhelix"]
    labels = {h.label if h.label is not None else index for index, h in enumerate(native.helices)}
    for edge in native_result["geometry"]["worst_edges"]:
        assert edge["from"]["helix_label"] in labels
        assert edge["to"]["helix_label"] in labels
    assert native.model_dump_json() == before
    assert review.review_design_bonds(native) == native_result
