"""Occupancy clouds for NAMD — the MD-specific half.

The clustering itself (PCA → k-means → medoid → drift/unimodal verdict) is the shared
engine-agnostic core and is covered by ``test_oxdna_occupancy.py``; nothing is re-tested
here. What IS MD-specific, and what these pin:

* which stages count as the ensemble — a restraint ramp is not free sampling;
* that MD's feature assembly does not go through oxDNA's, because MD has no ``a3`` and its
  positions are already backbone sites.

All fast: no PSF, no DCD, no MDAnalysis.
"""

import pytest

from backend.core.md_trajectory import _MD_PRODUCTION_MARKER, md_production_segments


def _segs(*labels):
    return [(f"seg{i}", lab, f"/tmp/{i}.dcd") for i, lab in enumerate(labels)]


# ── Which stages are the ensemble ─────────────────────────────────────────────────
def test_only_production_segments_are_clustered():
    """Every production builder puts the word in its stage label."""
    for label in (
        "50 ns fast production run",
        "2 ns production replica (seed 54321)",
        "310K NPT conservative production 0.5 ns unrestrained",
        "shell NVT production (COM-restrained, HMR 4 fs)",
    ):
        assert md_production_segments(_segs("300K NPT ENM k=0.5", label)) == [1], label


def test_a_restraint_ramp_that_encodes_k_in_the_label_is_excluded():
    """The bug a keyword-EXCLUSION filter had: these carry no enm/fixed/minim keyword, so
    excluding by keyword admitted the ENTIRE relaxation schedule. Measured against the 85
    MD jobs on this machine — 50K/100K/200K/300K NVT k=5.0 and the 11-step
    310K NPT k=5.0 → 0.01 ramp were all being clustered as if they were production."""
    for label in (
        "50K NVT k=5.0",
        "100K NVT k=5.0",
        "300K NVT k=5.0",
        "310K NPT k=5.0",
        "310K NPT k=0.5",
        "310K NPT k=0.01",
        "Vacuum ENRG-MD shape relaxation",
        "solvent equilibration (DNA position-restrained, NVT)",
    ):
        assert md_production_segments(_segs(label)) == [], label


def test_the_enm_ladder_and_its_terminal_unrestrained_stage_are_both_excluded():
    """ "300K NPT k=0" ends the ENM ladder unrestrained, but it is still equilibration —
    not a production run."""
    segs = _segs(
        "300K NPT ENM k=0.5",
        "300K NPT ENM k=0.1",
        "300K NPT ENM k=0.01",
        "300K NPT k=0",
    )
    assert md_production_segments(segs) == []


def test_the_qualification_stage_is_not_production():
    # Unrestrained, but a qualification probe rather than sampling.
    assert md_production_segments(_segs("310K NPT unrestrained qualification")) == []


def test_the_dna_fixed_settle_stage_and_minimisation_are_excluded():
    assert md_production_segments(_segs("300K NPT settle (DNA fixed)")) == []
    assert md_production_segments(_segs("Minimization ENM k=0.5")) == []


def test_every_production_segment_is_kept():
    segs = _segs("300K NPT ENM k=0.5", "5 ns production run", "10 ns production run")
    assert md_production_segments(segs) == [1, 2]


def test_no_production_means_NO_fallback():
    """Falling back to every segment would cluster the restraint ladder and answer a
    different question than the one asked."""
    assert md_production_segments(_segs("300K NPT ENM k=0.5", "300K NPT k=0")) == []
    assert md_production_segments([]) == []


def test_marker_matching_is_case_insensitive():
    assert md_production_segments(_segs("50 ns FAST PRODUCTION RUN")) == [0]
    assert _MD_PRODUCTION_MARKER == _MD_PRODUCTION_MARKER.lower()


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
    body = src[src.index('"""', src.index('"""') + 3) + 3 :]
    assert "occupancy_features" not in body
    assert "oxdna_backbone_sites" not in body
    # …but the CLUSTERING is shared, not reimplemented.
    assert "occupancy_clusters" in body
    assert "resolve_selection_keys" in body
    # …and so is the scoped re-superposition. `_superpose_on_subset` sat unused for a whole
    # release while both engines' docstrings claimed a scoped run was re-fitted, so pin the
    # CALL, not the existence of the function.
    assert "occupancy_fit_plan" in body
    assert "apply_fit_plan" in body


def test_md_scoped_run_is_refitted_and_reports_which_frame():
    """A scoped NAMD run must re-superpose, and the payload must say how: the fit frame
    changes the scientific answer (measured on job bfd050d2ce4c, 2hb_2xT 200 ns, 4 T
    inserts — global says drift, fit-on-selection says a recurrent 2-state flip)."""
    import inspect

    from backend.core import md_trajectory

    src = inspect.getsource(md_trajectory.md_occupancy)
    for field in (
        'res["fit"]',
        'res["fit_requested"]',
        'res["fit_note"]',
        'res["n_fit_points"]',
    ):
        assert field in src, f"{field} missing — a degraded fit would go unreported"


def test_md_occupancy_cache_key_separates_fit_frames():
    """The same region re-superposed differently is a different analysis; sharing a cache
    entry would serve the previous frame's answer."""
    from backend.api.routes_md import _md_occ_cache_key
    from backend.api.routes_oxdna import OccupancySelection

    segs = [("s", "5 ns production replica", "/tmp/none.dcd")]
    sel = OccupancySelection(extra_bases=[["xo1"]]).model_dump()
    a = _md_occ_cache_key(segs, "/tmp/none.psf", 200, 0, "nt", sel, "selection")
    b = _md_occ_cache_key(segs, "/tmp/none.psf", 200, 0, "nt", sel, "local")
    assert a != b


def test_md_occupancy_body_rejects_an_unknown_fit_mode():
    """The route 400s rather than silently analysing in some other frame."""
    import pytest
    from fastapi import HTTPException

    from backend.api import routes_md

    with pytest.raises(HTTPException) as e:
        import asyncio

        asyncio.run(
            routes_md._md_occupancy_impl(
                "nope",
                None,
                max_frames=200,
                n_clusters=0,
                basis="nt",
                refetch=False,
                fit="whatever",
            )
        )
    assert e.value.status_code == 400


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


def test_every_scoped_selection_shape_reaches_md_analysis_as_a_mapping(monkeypatch):
    """Regression: POST handed a Pydantic model to the cache signature, which calls
    ``.get``; therefore every non-empty NAMD scope failed before analysis. Exercise every
    declared selector alone plus a heterogeneous union."""
    import asyncio

    from backend.api import routes_md
    from backend.api.routes_oxdna import OccupancySelection

    monkeypatch.setattr(
        routes_md,
        "_md_traj_inputs",
        lambda _job: (
            "/tmp/fake.psf",
            "/tmp/fake.pdb",
            _segs("5 ns production"),
            object(),
        ),
    )
    seen = []

    async def fake_run(_request, _job, _kind, _fn, args, **_kwargs):
        seen.append(args[-2])
        return {"ready": False, "reason": "probe complete"}

    monkeypatch.setattr(routes_md, "_run_md_analysis", fake_run)
    selections = [
        OccupancySelection(cluster_ids=["c0"]),
        OccupancySelection(helix_ids=["h0"]),
        OccupancySelection(strand_ids=["s0"]),
        OccupancySelection(overhang_ids=["o0"]),
        OccupancySelection(domains=[["s0", 0]]),
        OccupancySelection(bases=[["h0", 4, "FORWARD"]]),
        OccupancySelection(extra_bases=[["xo0", 0]]),
        OccupancySelection(extensions=[["ext0", 0]]),
        OccupancySelection(
            cluster_ids=["c0"],
            strand_ids=["s0"],
            bases=[["h0", 4, "FORWARD"]],
            extra_bases=[["xo0", 0]],
        ),
    ]

    for selection in selections:
        result = asyncio.run(
            routes_md._md_occupancy_impl(
                "job",
                None,
                max_frames=20,
                n_clusters=0,
                basis="nt",
                refetch=False,
                selection=selection,
            )
        )
        assert result["reason"] == "probe complete"

    assert len(seen) == len(selections)
    for original, emitted in zip(selections, seen):
        assert isinstance(emitted, dict)
        assert emitted == original.model_dump()


def test_md_occupancy_body_rejects_an_undeclared_field():
    import pytest
    from pydantic import ValidationError

    from backend.api.routes_md import MdOccupancyBody

    with pytest.raises(ValidationError):
        MdOccupancyBody(align=True)  # oxDNA-only knob; MD frames are already aligned


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
    a = _md_occ_cache_key(
        segs,
        "/tmp/none.psf",
        200,
        0,
        "nt",
        OccupancySelection(helix_ids=["h0"]).model_dump(),
    )
    b = _md_occ_cache_key(
        segs,
        "/tmp/none.psf",
        200,
        0,
        "nt",
        OccupancySelection(helix_ids=["h1"]).model_dump(),
    )
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


def test_density_grid_is_normalized_and_reports_probability_isosurfaces():
    import numpy as np

    from backend.core.occupancy_core import occupancy_density_grids

    rng = np.random.default_rng(7)
    # One real duplex point plus two selected synthetic crossover bases.
    X = np.zeros((500, 9), dtype=float)
    X[:, 3:6] = rng.normal([1.0, 0.0, 0.0], 0.08, (500, 3))
    X[:, 6:9] = rng.normal([-1.0, 0.0, 0.0], 0.12, (500, 3))
    keys = [("h0", 1, "FORWARD"), ("__xb__", "xo", 0), ("__xb__", "xo", 1)]
    grids = occupancy_density_grids(X, keys, grid_size=20, sigma_nm=0.10)

    assert len(grids) == 2
    for g in grids:
        assert g["shape"] == [20, 20, 20]
        assert len(g["values"]) == 20**3
        assert sum(g["values"]) == pytest.approx(1.0, abs=2e-6)
        assert g["isovalues"]["50"] >= g["isovalues"]["80"] >= g["isovalues"]["95"]
        assert g["n_frames"] == 500
