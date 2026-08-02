"""Occupancy clouds for NAMD — the MD-specific half.

The clustering itself (PCA → k-means → medoid → drift/unimodal verdict) is the shared
engine-agnostic core and is covered by ``test_oxdna_occupancy.py``; nothing is re-tested
here. What IS MD-specific, and what these pin:

* which stages count as the ensemble — a restraint ramp is not free sampling;
* that MD's feature assembly does not go through oxDNA's, because MD has no ``a3`` and its
  positions are already backbone sites.

All fast: no PSF, no DCD, no MDAnalysis.
"""

from backend.core.md_trajectory import _MD_RESTRAINED_MARKERS, md_free_sampling_segments


def _segs(*labels):
    return [(f"seg{i}", lab, f"/tmp/{i}.dcd") for i, lab in enumerate(labels)]


# ── Which stages are the ensemble ─────────────────────────────────────────────────
def test_the_enm_restraint_ramp_is_not_free_sampling():
    """k=0.5 → 0.1 → 0.01 → none is a one-way relaxation. Clustering across it finds
    "early vs late" — a drift — and buries whatever the free ensemble does."""
    segs = _segs("300K NPT ENM k=0.5", "300K NPT ENM k=0.1",
                 "300K NPT ENM k=0.01", "300K NPT k=0")
    assert md_free_sampling_segments(segs) == [3]


def test_an_explicit_production_run_is_free_sampling():
    """The Run-production button emits `"<N> ns <fast|medium|conservative> production run"`
    segments with scale=None. Those are the ensemble this feature exists for, and they
    must qualify without the label needing a special case."""
    segs = _segs("300K NPT ENM k=0.5", "300K NPT k=0", "50 ns fast production run")
    assert md_free_sampling_segments(segs) == [1, 2]
    assert md_free_sampling_segments(_segs("100 ns conservative production run")) == [0]


def test_every_free_segment_is_kept():
    segs = _segs("300K NPT ENM k=0.5", "300K NPT k=0", "300K NPT k=0")
    assert md_free_sampling_segments(segs) == [1, 2]


def test_the_dna_fixed_settle_stage_is_excluded():
    # The cell is equilibrating around a FIXED solute — those frames carry no
    # conformational information at all.
    segs = _segs("300K NPT settle (DNA fixed)", "300K NPT k=0")
    assert md_free_sampling_segments(segs) == [1]


def test_minimisation_is_excluded():
    segs = _segs("Minimization ENM k=0.5", "300K NPT k=0")
    assert md_free_sampling_segments(segs) == [1]


def test_an_unfamiliar_protocol_falls_back_to_everything():
    """Degrade to "use it all, and say so" rather than to an empty ensemble — an unknown
    label must not silently mean "no frames"."""
    segs = _segs("some future stage", "another one")
    assert md_free_sampling_segments(segs) == [0, 1]


def test_a_run_that_never_left_restraints_falls_back_rather_than_returning_nothing():
    segs = _segs("300K NPT ENM k=0.5", "300K NPT ENM k=0.1")
    assert md_free_sampling_segments(segs) == [0, 1]


def test_marker_matching_is_case_insensitive():
    assert md_free_sampling_segments(_segs("300K NPT enm k=0.5", "300K NPT k=0")) == [1]
    assert all(m == m.lower() for m in _MD_RESTRAINED_MARKERS)


def test_empty_segment_list():
    assert md_free_sampling_segments([]) == []


# ── The wire contract MD must satisfy for the shared frontend ─────────────────────
def test_md_medoid_frames_use_the_same_six_float_stride():
    """The frontend maps keys→coordinates with one shared helper, so an MD medoid frame
    must be xyz+normal per key exactly like an oxDNA one."""
    import inspect

    from backend.core import md_trajectory

    src = inspect.getsource(md_trajectory.md_occupancy)
    # positions then normals, 3 floats each, per key
    assert "flat.extend((float(pos[i, 0]), float(pos[i, 1]), float(pos[i, 2])))" in src
    assert "flat.extend((float(nrm[i, 0]), float(nrm[i, 1]), float(nrm[i, 2])))" in src


def test_md_does_not_route_through_oxdna_feature_assembly():
    """MD has no a3 and its positions are already backbone sites; running oxDNA's
    occupancy_features over them would fabricate a backbone-site offset."""
    import inspect

    from backend.core import md_trajectory

    # Body only — the docstring names occupancy_features precisely to explain why MD
    # does NOT use it, so checking the whole source would match its own rationale.
    src = inspect.getsource(md_trajectory.md_occupancy)
    body = src[src.index('"""', src.index('"""') + 3) + 3:]
    assert "occupancy_features" not in body
    assert "oxdna_backbone_sites" not in body
    # …but the CLUSTERING is shared, not reimplemented.
    assert "occupancy_clusters" in body
    assert "resolve_selection_keys" in body


def test_md_occupancy_is_reachable_by_the_subprocess_runner():
    """_run_md_analysis resolves the qualname from backend.core.md_trajectory, so the
    function must live there — a module move would break the route with an import error
    that only appears at request time."""
    import importlib

    mod = importlib.import_module("backend.core.md_trajectory")
    assert callable(getattr(mod, "md_occupancy", None))


def test_selection_vocabulary_is_shared_with_oxdna():
    """MD and oxDNA emit the same nucleotide keys, so one selection model serves both —
    a second one would drift."""
    from backend.api.routes_md import MdOccupancyBody
    from backend.api.routes_oxdna import OccupancySelection

    assert MdOccupancyBody.model_fields["selection"].annotation is not None
    body = MdOccupancyBody(selection=OccupancySelection(helix_ids=["h0"]))
    assert body.selection.helix_ids == ["h0"]


def test_md_occupancy_body_rejects_an_undeclared_field():
    import pytest
    from pydantic import ValidationError

    from backend.api.routes_md import MdOccupancyBody

    with pytest.raises(ValidationError):
        MdOccupancyBody(align=True)      # oxDNA-only knob; MD frames are already aligned


def test_md_occupancy_cache_key_self_invalidates_on_growth(tmp_path):
    """A running job's DCD grows; the key carries size+mtime so the answer cannot go
    stale — the property oxDNA's _aligned_cache_key relies on."""
    from backend.api.routes_md import _md_occ_cache_key

    dcd = tmp_path / "a.dcd"
    psf = tmp_path / "a.psf"
    dcd.write_bytes(b"x" * 10)
    psf.write_bytes(b"p")
    segs = [("s", "300K NPT k=0", dcd)]
    k1 = _md_occ_cache_key(segs, psf, 200, 0, "nt", None)

    dcd.write_bytes(b"x" * 20)
    k2 = _md_occ_cache_key(segs, psf, 200, 0, "nt", None)
    assert k1 != k2


def test_md_occupancy_cache_key_separates_scopes():
    from backend.api.routes_md import _md_occ_cache_key
    from backend.api.routes_oxdna import OccupancySelection

    segs = [("s", "300K NPT k=0", "/tmp/none.dcd")]
    a = _md_occ_cache_key(segs, "/tmp/none.psf", 200, 0, "nt",
                          OccupancySelection(helix_ids=["h0"]).model_dump())
    b = _md_occ_cache_key(segs, "/tmp/none.psf", 200, 0, "nt",
                          OccupancySelection(helix_ids=["h1"]).model_dump())
    assert a != b


def test_there_is_no_opt_in_for_restrained_stages():
    """An occupancy cloud over relaxation frames describes the restraint ramp, not the
    structure, so the option was removed rather than defaulted off."""
    import inspect

    from backend.api import routes_md
    from backend.core import md_trajectory

    assert "all_stages" not in inspect.signature(md_trajectory.md_occupancy).parameters
    assert "all_stages" not in routes_md.MdOccupancyBody.model_fields
    assert "all_stages" not in inspect.signature(routes_md.get_md_occupancy).parameters
