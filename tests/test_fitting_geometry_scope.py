"""Anchor-only geometry uses the same native coordinates and complete pose context."""

import pytest

from backend.core import design_geometry as geometry
from backend.core.models import Design, LatticeType, StrandExtension
from backend.core.sweep import SweepRequest, build_sweep


@pytest.fixture(params=list(LatticeType))
def swept(request):
    design = build_sweep(
        Design(lattice_type=request.param),
        SweepRequest(
            cells=[(0, 0), (0, 1), (1, 0), (1, 1)],
            points_nm=[(0, 0, 0), (2, 0, 8), (5, 0, 16)],
            ligate_adjacent=False,
        ),
    )
    strand = design.strands[0]
    marked = strand.model_copy(
        update={
            "domains": [
                d.model_copy(update={"overhang_id": "attachment"})
                for d in strand.domains
            ]
        }
    )
    return design.copy_with(strands=[marked, *design.strands[1:]])


@pytest.mark.parametrize("kind", ["strand", "overhang", "empty"])
def test_scoped_geometry_is_exact_full_geometry_subset(swept, kind, monkeypatch):
    full = geometry.fitting_geometry(swept)
    strand = swept.strands[0]
    ids = {d.helix_id for d in strand.domains} if kind != "empty" else set()
    args = (
        {"strand_ids": {strand.id}}
        if kind == "strand"
        else {"overhang_ids": {"attachment"}}
        if kind == "overhang"
        else {"strand_ids": set()}
    )
    calls = []
    original = geometry.native_full_arrays_for_helix

    def read(helix, design, **kwargs):
        assert design is swept  # Keep other helices for arm centroids and clusters.
        calls.append(helix.id)
        return original(helix, design, **kwargs)

    monkeypatch.setattr(geometry, "native_full_arrays_for_helix", read)
    result = geometry.fitting_geometry(swept, **args)
    assert result == [n for n in full if n["helix_id"] in ids]
    assert set(calls) == ids
    assert len(calls) < len(swept.helices)


def test_extension_dependencies_keep_full_geometry(swept):
    design = swept.copy_with(
        extensions=[
            StrandExtension(
                strand_id=swept.strands[0].id, end="five_prime", sequence="AAA"
            )
        ]
    )
    assert geometry.fitting_geometry(
        design, strand_ids={design.strands[0].id}
    ) == geometry.fitting_geometry(design)


def test_standalone_midpoint_exits_before_geometry(swept, monkeypatch):
    from backend.core.direct_relax import duplex_midpoint_placement

    def unexpected(*args, **kwargs):
        pytest.fail("A standalone handle cannot be seated between two embedded roots")

    monkeypatch.setattr(geometry, "fitting_geometry", unexpected)
    assert duplex_midpoint_placement(swept, "attachment", "missing") is None
