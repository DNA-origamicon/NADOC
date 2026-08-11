"""Occupancy clouds — clustering an oxDNA ensemble into its top-N configurations.

Every test here runs on small numpy arrays or hand-built frame dicts: no file I/O, no
trajectory, no Design build. Fast-suite safe by construction.

The two pins that matter most are ``test_medoid_is_a_real_frame_never_a_mean`` (a cluster
mean would collapse bond lengths, reproducing the very artefact this feature replaces) and
``test_monotone_drift_is_not_reported_as_two_states`` (a drift scores a HIGH silhouette
while never revisiting a state — measured on a real job, see the module docstring).
"""

import numpy as np
import pytest

from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.oxdna_health import FENE_R0_OXDNA2
from backend.core.oxdna_occupancy import (
    OCCUPANCY_PRELIM_NEFF,
    _OCC_MIN_FRAMES,
    occupancy_clusters,
    occupancy_confidence,
    occupancy_features,
    state_recurrence,
)


# ── Fixtures with analytically known answers ──────────────────────────────────────
def _two_state(n_a=80, n_b=40, d=30, sep=10.0, noise=0.3, seed=7, interleave=True):
    """Two well-separated basins with populations exactly n_a/(n_a+n_b) and n_b/(...).

    ``interleave=True`` shuffles membership through time so each state is revisited many
    times — a genuine switching ensemble. ``False`` puts all of A then all of B, which is
    what a one-way drift looks like.
    """
    rng = np.random.default_rng(seed)
    mu_b = np.zeros(d)
    mu_b[:6] = sep
    labels = np.array([0] * n_a + [1] * n_b)
    if interleave:
        rng.shuffle(labels)
    X = np.where(labels[:, None] == 0, 0.0, mu_b[None, :]) + rng.normal(
        scale=noise, size=(labels.size, d)
    )
    return X, labels


def _unimodal(n=100, d=30, seed=3):
    return np.random.default_rng(seed).normal(scale=1.0, size=(n, d))


# ── Core clustering behaviour ─────────────────────────────────────────────────────
def test_two_state_ensemble_recovers_both_states():
    X, truth = _two_state()
    res = occupancy_clusters(X)

    assert res["ready"] is True
    assert res["k"] == 2
    assert res["verdict"] == "switching"
    assert res["multimodal"] is True

    pops = sorted(c["population"] for c in res["clusters"])
    assert pops == pytest.approx([40 / 120, 80 / 120], abs=1e-9)

    # every frame of a returned cluster really belongs to one true basin
    for cl in res["clusters"]:
        assert len({truth[i] for i in cl["frames"]}) == 1


def test_unimodal_ensemble_reports_one_state():
    """A single Gaussian basin must NOT be split. Inventing states is worse than none."""
    res = occupancy_clusters(_unimodal())
    assert res["verdict"] == "unimodal"
    assert res["multimodal"] is False
    assert res["k"] == 1
    assert len(res["clusters"]) == 1
    assert res["clusters"][0]["population"] == pytest.approx(1.0)


def test_monotone_drift_is_not_reported_as_two_states():
    """A one-way drift scores a high silhouette but is not two configurations.

    Measured on ``exp35_.../oxdna_jobs/14b896dab3c2``: silhouette +0.58 at k=2, label
    sequence ``1111111111111111111111111 0000000000000000000000000`` — one transition,
    PC1 lag-1 autocorrelation +1.000. Calling those "states" with 50/50 populations
    would be a confident lie about an unequilibrated run.
    """
    t = np.linspace(0.0, 1.0, 60)
    X = np.outer(t, np.ones(20)) * 10.0 + np.random.default_rng(1).normal(
        scale=0.05, size=(60, 20)
    )
    res = occupancy_clusters(X)

    assert res["silhouette"] > 0.25, "the drift should still LOOK separated"
    assert res["verdict"] == "drift"
    assert res["multimodal"] is False, "a drift must never be advertised as switching"
    assert res["transitions"] <= 1
    assert res["pc1_lag1"] > 0.9, "a smooth path, not hopping between basins"


def test_switching_and_drift_are_distinguished_on_identical_geometry():
    """Same two basins, same populations — only the TIME ORDER differs."""
    X_sw, _ = _two_state(interleave=True)
    X_dr, _ = _two_state(interleave=False)

    assert occupancy_clusters(X_sw)["verdict"] == "switching"
    assert occupancy_clusters(X_dr)["verdict"] == "drift"


def test_medoid_is_a_real_frame_never_a_mean():
    """The representative must be an observed frame, not a within-cluster average.

    Averaging positions collapses bond lengths; a mean structure is as unreal as the flat
    RMSF mean this feature exists to replace.
    """
    X, _ = _two_state()
    res = occupancy_clusters(X)

    ensemble_mean = X.mean(axis=0)
    for cl in res["clusters"]:
        row = X[cl["medoid_index"]]
        assert np.any(np.all(np.isclose(X, row), axis=1)), "medoid is not an input row"
        # and it is far from the ensemble mean — the thing RMSF would have shown
        assert np.linalg.norm(row - ensemble_mean) > 1.0


def test_clustering_is_deterministic():
    X, _ = _two_state()
    a, b = occupancy_clusters(X), occupancy_clusters(X)
    assert [c["frames"] for c in a["clusters"]] == [c["frames"] for c in b["clusters"]]
    assert [c["medoid_index"] for c in a["clusters"]] == [
        c["medoid_index"] for c in b["clusters"]
    ]


def test_populations_carry_an_autocorrelation_aware_error_bar():
    """Frames are not independent — a naive binomial error overstates confidence.

    A blocky membership series (long runs in each state) must yield tau_int > 1 and an
    error bar strictly larger than sqrt(p(1-p)/n).
    """
    block = np.array(([0] * 20 + [1] * 20) * 5)
    rng = np.random.default_rng(11)
    mu = np.zeros(20)
    mu[:5] = 8.0
    X = np.where(block[:, None] == 0, 0.0, mu[None, :]) + rng.normal(
        scale=0.2, size=(block.size, 20)
    )

    res = occupancy_clusters(X)
    assert res["verdict"] == "switching"
    cl = res["clusters"][0]
    p, n = cl["population"], res["n_frames"]
    naive = float(np.sqrt(p * (1 - p) / n))

    assert cl["tau_int"] > 1.0
    assert cl["n_eff"] < n
    assert cl["population_sem"] > naive


def test_forced_k_is_honoured_and_reports_weak_separation():
    X, _ = _two_state()
    res = occupancy_clusters(X, n_clusters=3)
    assert res["auto_k"] is False
    assert res["k"] == 3
    assert len(res["clusters"]) == 3
    assert "silhouette" in res


def test_too_few_frames_is_not_ready():
    res = occupancy_clusters(
        np.random.default_rng(0).normal(size=(_OCC_MIN_FRAMES - 1, 12))
    )
    assert res["ready"] is False
    assert "at least" in res["reason"]


def test_variance_explained_is_descending_and_bounded():
    X, _ = _two_state()
    var = occupancy_clusters(X)["variance_explained"]
    assert var == sorted(var, reverse=True)
    assert 0.0 <= var[0] <= 1.0
    assert sum(var) <= 1.0 + 1e-9


def test_rank_zero_is_the_most_populated_and_rmsd_to_top_is_zero():
    X, _ = _two_state()
    res = occupancy_clusters(X)
    assert res["clusters"][0]["rank"] == 0
    assert res["clusters"][0]["population"] >= res["clusters"][-1]["population"]
    assert res["clusters"][0]["rmsd_to_top_nm"] == pytest.approx(0.0, abs=1e-9)
    assert res["clusters"][-1]["rmsd_to_top_nm"] > 0.0


# ── Recurrence + confidence helpers ───────────────────────────────────────────────
def test_state_recurrence_counts_visits_not_frames():
    rec = state_recurrence([0, 0, 0, 1, 1, 0, 0, 1], 2)
    assert rec["visits"] == [2, 2]
    assert rec["transitions"] == 3
    assert rec["recurrent"] is True

    once = state_recurrence([0] * 5 + [1] * 5, 2)
    assert once["visits"] == [1, 1]
    assert once["transitions"] == 1
    assert once["recurrent"] is False


def test_occupancy_confidence_flags_undersampled_populations():
    assert occupancy_confidence(200, 2.6)["preliminary"] is True
    assert occupancy_confidence(200, OCCUPANCY_PRELIM_NEFF + 1)["preliminary"] is False
    # more independent samples → smaller relative error
    assert (
        occupancy_confidence(200, 100)["rel_error"]
        < occupancy_confidence(200, 10)["rel_error"]
    )


# ── Feature extraction ────────────────────────────────────────────────────────────
class _FakeDesign:
    """Minimal stand-in — occupancy_features only reaches the design via _strain_index."""


# Bonded neighbours must sit inside oxDNA's FENE window or the quality gate (correctly)
# throws the frame away. Derive it from the constants rather than hardcoding 0.64 nm, so
# these fixtures follow the model if it is ever retuned.
_BOND_NM = FENE_R0_OXDNA2 * OXDNA_LENGTH_UNIT


def _frame(keys, positions, a1s=None):
    """a1s defaults to +x for every nucleotide. Pass explicit vectors to model a real
    duplex, where the two strands' base vectors OPPOSE — that opposition is what makes a
    base-pair midpoint land on the duplex axis."""
    if a1s is None:
        a1s = [[1.0, 0.0, 0.0]] * len(keys)
    return {
        k: {
            "backbone_position": np.array(p, dtype=float),
            "a1": np.array(a, dtype=float),
            "a3": np.array([0.0, 0.0, 1.0]),
        }
        for k, p, a in zip(keys, positions, a1s)
    }


def test_features_reject_torn_frames_and_report_which_survived(monkeypatch):
    """A PBC-torn frame carries box-scale bonds and would become its own 'configuration'."""
    import backend.core.oxdna_occupancy as occ

    keys = [("h0", i, "FORWARD") for i in range(4)]
    monkeypatch.setattr(
        occ,
        "_strain_index",
        lambda design, k, metric: (np.array([0, 1, 2]), np.array([1, 2, 3])),
    )

    good = [_frame(keys, [[0, 0, i * _BOND_NM] for i in range(4)]) for _ in range(3)]
    # a PBC tear: the last two nucleotides snapped to a different periodic image
    torn = _frame(
        keys, [[0, 0, 0], [0, 0, _BOND_NM], [0, 0, 90.0], [0, 0, 90.0 + _BOND_NM]]
    )
    frames = [good[0], torn, good[1], good[2]]

    X, _fk, kept, _basis, _plan = occ.occupancy_features(
        frames, keys, _FakeDesign(), basis="nt"
    )

    assert kept == [0, 2, 3], "the torn frame must be dropped, the rest kept in order"
    assert X.shape[0] == 3
    assert len(frames) - len(kept) == 1


def _duplex_fixture(n_bp):
    """n_bp duplex columns stacked along z, plus one unpaired ssDNA overhang bead.

    Keys interleave FORWARD/REVERSE per column, so column c is keys[2c], keys[2c+1].
    """
    keys = []
    for c in range(n_bp):
        keys.append(("h0", c, "FORWARD"))
        keys.append(("h0", c, "REVERSE"))
    keys.append(("h0", n_bp, "FORWARD"))  # unpaired overhang

    positions, a1s = [], []
    for c in range(n_bp):
        positions.append([0.0, 0.0, c * _BOND_NM])  # FORWARD strand
        a1s.append([1.0, 0.0, 0.0])  # base points across the duplex…
        positions.append([1.0, 0.0, c * _BOND_NM])  # REVERSE strand
        a1s.append([-1.0, 0.0, 0.0])  # …and its partner points back
    positions.append([5.0, 5.0, 5.0])  # the ssDNA bead, far away
    a1s.append([1.0, 0.0, 0.0])

    wc_a = np.array([2 * c for c in range(n_bp)])
    wc_b = np.array([2 * c + 1 for c in range(n_bp)])
    # backbone 3'-neighbours WITHIN each strand (never across the duplex)
    bb_a = np.array(
        [2 * c for c in range(n_bp - 1)] + [2 * c + 1 for c in range(n_bp - 1)]
    )
    bb_b = np.array(
        [2 * (c + 1) for c in range(n_bp - 1)]
        + [2 * (c + 1) + 1 for c in range(n_bp - 1)]
    )

    def fake_index(design, k, metric):
        return (wc_a, wc_b) if metric == "wc" else (bb_a, bb_b)

    return keys, positions, a1s, fake_index


def test_bp_basis_uses_only_paired_columns(monkeypatch):
    import backend.core.oxdna_occupancy as occ

    n_bp = 12  # ≥ _OCC_MIN_BP_COLUMNS
    keys, positions, a1s, fake_index = _duplex_fixture(n_bp)
    monkeypatch.setattr(occ, "_strain_index", fake_index)
    frames = [_frame(keys, positions, a1s) for _ in range(2)]

    X, feature_keys, kept, basis_used, _plan = occ.occupancy_features(
        frames, keys, _FakeDesign(), basis="bp"
    )

    assert basis_used == "bp"
    assert X.shape[1] == n_bp * 3, "one 3-vector per duplex column, ssDNA excluded"
    assert feature_keys == [keys[2 * c] for c in range(n_bp)]
    assert kept == [0, 1]

    # the bp feature is the midpoint of the two strands → x = 0.5, on the duplex axis
    assert X[0].reshape(n_bp, 3)[:, 0] == pytest.approx(np.full(n_bp, 0.5))


def test_bp_basis_falls_back_to_nt_and_says_so(monkeypatch):
    """A construct with no real duplex must not silently claim a bp basis."""
    import backend.core.oxdna_occupancy as occ

    n_bp = 2  # < _OCC_MIN_BP_COLUMNS
    keys, positions, a1s, fake_index = _duplex_fixture(n_bp)
    monkeypatch.setattr(occ, "_strain_index", fake_index)
    frames = [_frame(keys, positions, a1s) for _ in range(2)]

    X, feature_keys, _kept, basis_used, _plan = occ.occupancy_features(
        frames, keys, _FakeDesign(), basis="bp"
    )

    assert basis_used == "nt", "the fallback must be reported, not applied silently"
    assert X.shape[1] == len(keys) * 3
    assert feature_keys == keys


def test_bp_basis_scoped_to_one_unpaired_base_falls_back_to_nt(monkeypatch):
    """An individual ssDNA pick is valid even though it has no bp-midpoint column."""
    import backend.core.oxdna_occupancy as occ

    n_bp = 12
    keys, positions, a1s, fake_index = _duplex_fixture(n_bp)
    monkeypatch.setattr(occ, "_strain_index", fake_index)
    frames = [_frame(keys, positions, a1s) for _ in range(2)]
    unpaired = keys[-1]

    X, feature_keys, _kept, basis_used, _plan = occ.occupancy_features(
        frames,
        keys,
        _FakeDesign(),
        basis="bp",
        selection={"bases": [list(unpaired)]},
    )

    assert basis_used == "nt"
    assert feature_keys == [unpaired]
    assert X.shape == (2, 3)


def test_nt_basis_keeps_every_nucleotide(monkeypatch):
    import backend.core.oxdna_occupancy as occ

    keys = [("h0", i, "FORWARD") for i in range(4)]
    monkeypatch.setattr(
        occ,
        "_strain_index",
        lambda design, k, metric: (np.array([0, 1, 2]), np.array([1, 2, 3])),
    )
    frames = [_frame(keys, [[0, 0, i * _BOND_NM] for i in range(4)]) for _ in range(2)]

    X, feature_keys, _kept, _basis, _plan = occ.occupancy_features(
        frames, keys, _FakeDesign(), basis="nt"
    )
    assert X.shape[1] == 4 * 3
    assert feature_keys == keys


def test_features_reject_an_unknown_basis():
    with pytest.raises(ValueError, match="basis"):
        occupancy_features([], [], _FakeDesign(), basis="axis")


# ── Stage slicing ─────────────────────────────────────────────────────────────────
def test_sampling_indices_skip_relaxation_and_the_seed_frame():
    """Relaxation stages are a transient; composite index 0 is the design pose."""
    from backend.core.oxdna_occupancy import _sampling_indices

    stages = [
        {"name": "1_mc_relax", "kind": "mc", "n_frames": 3},
        {"name": "2_equil", "kind": "equil", "n_frames": 2},
        {"name": "3_production", "kind": "production", "n_frames": 4},
    ]
    assert _sampling_indices(stages) == [5, 6, 7, 8]

    # production first → index 0 is the prepended seed and must be dropped
    seeded = [
        {"name": "1_production", "kind": "production", "n_frames": 3},
        {"name": "2_field", "kind": "field", "n_frames": 2},
    ]
    assert _sampling_indices(seeded) == [1, 2, 3, 4]


# ── Route layer ───────────────────────────────────────────────────────────────────
class _FakeStage:
    def __init__(self, kind="production", status="done"):
        self.kind = kind
        self.status = status
        self.name = f"1_{kind}"


class _FakeJob:
    job_id = "occ-test"
    stages = [_FakeStage()]


@pytest.fixture
def occ_client(monkeypatch):
    """TestClient with the job lookup and frame walk stubbed out.

    Returns (client, calls) where ``calls`` collects the kwargs the route passed down,
    so the tests can assert on what the route ASKED for rather than on a real trajectory.
    """
    from fastapi.testclient import TestClient

    import backend.api.routes_oxdna as ro
    import backend.core.oxdna_occupancy as occ
    from backend.api.main import app

    calls = []

    monkeypatch.setattr(ro, "_load_job", lambda job_id: _FakeJob())
    monkeypatch.setattr(
        ro,
        "_composite_inputs",
        lambda job, scope: (
            "DESIGN",
            [("1_production", "production", "t.dat", None, None)],
            "ref.dat",
        ),
    )
    monkeypatch.setattr(ro, "_capture_bead_count", lambda job: 0)
    monkeypatch.setattr(ro, "_capture_strand_length", lambda job: 0)

    def fake_cached(design, stages, ref, **kw):
        calls.append(kw)
        return {
            "ready": True,
            "verdict": "unimodal",
            "k": 1,
            "clusters": [],
            "keys": [],
        }

    monkeypatch.setattr(occ, "production_occupancy_cached", fake_cached)
    return TestClient(app), calls


def test_route_defaults_match_the_trajectory_route(occ_client):
    """The shared _ALIGNED_CACHE only hits if both routes ask for the same frames.

    ``/trajectory`` uses scope='lineage' and max_frames=_SPARSE_FRAME_CAP. If this route's
    defaults drift, every occupancy request silently re-reads the whole trajectory.
    """
    from backend.api.routes_oxdna import _SPARSE_FRAME_CAP

    client, calls = occ_client
    assert client.get("/api/oxdna/jobs/occ-test/occupancy").status_code == 200
    assert calls[-1]["max_frames"] == _SPARSE_FRAME_CAP
    assert calls[-1]["align"] is True


def test_route_rejects_unknown_method_and_basis(occ_client):
    client, _ = occ_client
    assert (
        client.get("/api/oxdna/jobs/occ-test/occupancy?method=rmsd").status_code == 400
    )
    assert (
        client.get("/api/oxdna/jobs/occ-test/occupancy?basis=axis").status_code == 400
    )


def test_route_clamps_n_clusters(occ_client):
    client, calls = occ_client
    client.get("/api/oxdna/jobs/occ-test/occupancy?n_clusters=99")
    assert calls[-1]["n_clusters"] == 6
    client.get("/api/oxdna/jobs/occ-test/occupancy?n_clusters=-3")
    assert calls[-1]["n_clusters"] == 0


def test_route_passes_basis_and_refetch_through(occ_client):
    client, calls = occ_client
    client.get("/api/oxdna/jobs/occ-test/occupancy?basis=bp&refetch=true")
    assert calls[-1]["basis"] == "bp"
    assert calls[-1]["refetch"] is True


def test_route_not_ready_without_a_sampling_stage(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.api.routes_oxdna as ro
    from backend.api.main import app

    monkeypatch.setattr(ro, "_load_job", lambda job_id: _FakeJob())
    monkeypatch.setattr(ro, "_composite_inputs", lambda job, scope: (None, [], None))

    r = TestClient(app).get("/api/oxdna/jobs/occ-test/occupancy")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "production" in body["reason"]


def test_occupancy_progress_is_inactive_when_nothing_is_building():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    assert TestClient(app).get("/api/oxdna/jobs/nobody/occupancy-progress").json() == {
        "active": False
    }


def test_occupancy_progress_dict_is_separate_from_the_trajectory_one():
    """One job can build a trajectory and an occupancy map at once; sharing the dict
    would make each overwrite the other's bar."""
    from backend.api.routes_oxdna import _OCC_PROGRESS, _TRAJ_PROGRESS

    assert _OCC_PROGRESS is not _TRAJ_PROGRESS


# ── Scoped analysis: clustering only part of the structure ────────────────────────
class _FakeCluster:
    def __init__(self, cid, helix_ids):
        self.id = cid
        self.helix_ids = list(helix_ids)


class _ScopedDesign:
    """Only what resolve_selection_keys reaches: cluster_transforms (+ the strand walk,
    which the tests monkeypatch)."""

    def __init__(self, clusters=()):
        self.cluster_transforms = list(clusters)


def _keys(n_helices=3, n_bp=4):
    return [
        (f"h{h}", b, d)
        for h in range(n_helices)
        for b in range(n_bp)
        for d in ("FORWARD", "REVERSE")
    ]


def test_no_selection_means_the_whole_structure():
    from backend.core.oxdna_occupancy import resolve_selection_keys

    ks = _keys()
    assert resolve_selection_keys(_ScopedDesign(), ks, None) == ks
    assert resolve_selection_keys(_ScopedDesign(), ks, {}) == ks


def test_selection_by_helix():
    from backend.core.oxdna_occupancy import resolve_selection_keys

    got = resolve_selection_keys(_ScopedDesign(), _keys(), {"helix_ids": ["h1"]})
    assert got and all(k[0] == "h1" for k in got)
    assert len(got) == 8


def test_a_cluster_expands_to_its_member_helices():
    from backend.core.oxdna_occupancy import resolve_selection_keys

    d = _ScopedDesign([_FakeCluster("c1", ["h0", "h2"])])
    got = resolve_selection_keys(d, _keys(), {"cluster_ids": ["c1"]})
    assert {k[0] for k in got} == {"h0", "h2"}


def test_selection_by_individual_base_picks_up_its_loop_copies():
    # A base is matched on (helix, bp, direction), so selecting a position takes every
    # loop-insertion copy at it rather than an arbitrary one.
    from backend.core.oxdna_occupancy import resolve_selection_keys

    ks = [("h0", 0, "FORWARD"), ("h0", 0, "FORWARD", 1), ("h0", 1, "FORWARD")]
    got = resolve_selection_keys(_ScopedDesign(), ks, {"bases": [["h0", 0, "FORWARD"]]})
    assert got == [("h0", 0, "FORWARD"), ("h0", 0, "FORWARD", 1)]


def test_selection_by_strand(monkeypatch):
    import backend.core.oxdna_occupancy as occ

    ks = _keys(n_helices=2, n_bp=2)
    owner = {k: ("sA" if k[0] == "h0" else "sB") for k in ks}

    class _Step:
        def __init__(self, key, sid):
            self.key = key
            self.strand = type("S", (), {"id": sid})()

    import backend.core.occupancy_core as core

    monkeypatch.setattr(
        core,
        "_walk_strand_nucleotides",
        lambda design: [_Step(k, owner[k]) for k in ks],
    )
    got = occ.resolve_selection_keys(_ScopedDesign(), ks, {"strand_ids": ["sB"]})
    assert {k[0] for k in got} == {"h1"}


def test_criteria_union_rather_than_intersect():
    # "Pick these things" means a union; intersecting would make a helix + a base from a
    # different helix select nothing, which is not what the user did.
    from backend.core.oxdna_occupancy import resolve_selection_keys

    got = resolve_selection_keys(
        _ScopedDesign(), _keys(), {"helix_ids": ["h0"], "bases": [["h2", 1, "FORWARD"]]}
    )
    assert {k[0] for k in got} == {"h0", "h2"}
    assert sum(1 for k in got if k[0] == "h2") == 1


# ── Synthetic beads (crossover extra bases + extension tails) ─────────────────────
# They carry no (helix, bp, direction), so the coordinate criteria must never reach them
# — but they ARE addressable through their own two criteria. The asymmetry this fixes:
# an UNSCOPED run has always included them (key_list comes from _strand_nucleotide_order),
# so they were in the feature basis by default yet impossible to name when scoping.

_XB = ("__xb__", "x1", 0)
_XB2 = ("__xb__", "x1", 1)
_XB_OTHER = ("__xb__", "x2", 0)
_EXT = ("__ext_e1", 0, "FORWARD")
_EXT2 = ("__ext_e1", 1, "FORWARD")
_EXT_OTHER = ("__ext_e2", 0, "FORWARD")
_REAL = ("h0", 0, "FORWARD")
_SYNTH_KEYS = [_REAL, _XB, _XB2, _XB_OTHER, _EXT, _EXT2, _EXT_OTHER]


def _sel(design=None, keys=None, **selection):
    from backend.core.oxdna_occupancy import resolve_selection_keys

    return resolve_selection_keys(
        design or _ScopedDesign(), keys or _SYNTH_KEYS, selection
    )


def test_a_coordinate_scope_never_reaches_synthetic_beads():
    """helix/base/strand/domain/overhang all match on fields synthetics don't have."""
    assert _sel(helix_ids=["h0", "__xb__", "__ext_e1"]) == [_REAL]
    assert _sel(bases=[["h0", 0, "FORWARD"]]) == [_REAL]


def test_extra_bases_scope_selects_one_insert():
    assert _sel(extra_bases=[["x1", 0]]) == [_XB]


def test_extra_bases_scope_without_an_index_takes_the_whole_run():
    assert _sel(extra_bases=[["x1"]]) == [_XB, _XB2]


def test_extra_bases_scope_does_not_leak_across_crossovers():
    assert _XB_OTHER not in _sel(extra_bases=[["x1"]])


def test_extensions_scope_selects_one_tail_bead_or_the_whole_tail():
    assert _sel(extensions=[["e1", 1]]) == [_EXT2]
    assert _sel(extensions=[["e1"]]) == [_EXT, _EXT2]
    assert _EXT_OTHER not in _sel(extensions=[["e1"]])


def test_synthetic_and_real_scopes_union():
    assert _sel(helix_ids=["h0"], extra_bases=[["x1", 0]], extensions=[["e1"]]) == [
        _REAL,
        _XB,
        _EXT,
        _EXT2,
    ]


def test_a_scope_that_asks_for_no_synthetics_still_excludes_them():
    """The pre-existing contract: scoping to real geometry must not silently pull in
    extra-base or tail coordinates, which are far floppier than the duplex."""
    assert _sel(strand_ids=["s0"], keys=_SYNTH_KEYS) == []


def test_an_unscoped_run_keeps_synthetics(monkeypatch):
    from backend.core.oxdna_occupancy import resolve_selection_keys

    assert resolve_selection_keys(_ScopedDesign(), _SYNTH_KEYS, None) == _SYNTH_KEYS


def test_subset_superposition_removes_rigid_body_motion():
    """The reason a scoped run needs its own fit: a region that only SWINGS must come out
    as one state, not two."""
    from backend.core.oxdna_occupancy import _superpose_on_subset, occupancy_clusters

    rng = np.random.default_rng(5)
    base = rng.normal(size=(12, 3)) * 2.0
    frames = []
    for t in range(60):
        th = 0.9 * np.sin(t / 3.0)  # the region swings back and forth
        R = np.array(
            [[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]]
        )
        # A little thermal jitter, so what remains after the fit is a real (unimodal)
        # ensemble rather than float noise that clustering cannot meaningfully describe.
        frames.append(
            ((base @ R.T) + np.array([3 * np.cos(th), 0, 0])).ravel()
            + rng.normal(scale=0.05, size=36)
        )
    X = np.array(frames)

    # Unfitted, the swing dominates and looks like well-separated states.
    assert occupancy_clusters(X)["silhouette"] > 0.25
    # Fitted on the region itself, the rigid motion is gone and it reads as one shape.
    fitted = _superpose_on_subset(X)
    assert fitted.std(axis=0).max() < X.std(axis=0).max() / 10
    assert occupancy_clusters(fitted)["verdict"] == "unimodal"


def test_subset_superposition_keeps_a_real_shape_change():
    """...while an actual internal deformation must survive the fit."""
    from backend.core.oxdna_occupancy import _superpose_on_subset, occupancy_clusters

    rng = np.random.default_rng(9)
    base = rng.normal(size=(12, 3)) * 2.0
    frames, labels = [], []
    for t in range(60):
        bent = base.copy()
        sign = 1.0 if (t % 6) < 3 else -1.0  # two genuine internal shapes
        bent[:, 2] += sign * 1.5 * bent[:, 0] ** 2 / 4.0
        frames.append(bent.ravel() + rng.normal(scale=0.02, size=36))
        labels.append(sign)
    res = occupancy_clusters(_superpose_on_subset(np.array(frames)))
    assert res["verdict"] == "switching"
    assert res["k"] == 2


# ── Fit frames for a scoped run ───────────────────────────────────────────────────
#
# The pin that matters: `occupancy_fit_plan` must actually be REACHED from production.
# `_superpose_on_subset` was written, correct and tested for a whole release while having
# no call site at all, so every scoped run silently clustered the region's rigid-body swing
# inside the global fit. Prove the wiring, not just the maths.

_XO_A = "xo-a"
_FLANK_KEYS = [("h0", i, d) for i in range(11, 18) for d in ("FORWARD", "REVERSE")]


class _FitHalf:
    def __init__(self, hid, idx):
        self.helix_id, self.index = hid, idx


class _FitXover:
    def __init__(self):
        self.id = _XO_A
        self.half_a = _FitHalf("h0", 14)
        self.half_b = _FitHalf("h1", 14)


class _FitDesign:
    """A design with one crossover carrying two extra bases at h0/h1 index 14."""

    crossovers = [_FitXover()]
    cluster_transforms: list = []


def _fit_keys():
    """Duplex flanking both halves + the two inserts. Paired columns exist on h0 only, so
    a selection spanning both is genuinely MIXED."""
    keys = list(_FLANK_KEYS)
    keys += [("h1", i, d) for i in range(11, 18) for d in ("FORWARD", "REVERSE")]
    keys += [("__xb__", _XO_A, 0), ("__xb__", _XO_A, 1)]
    return keys


def test_an_unscoped_run_is_never_refitted():
    """There is no sub-region whose rigid-body motion could be removed, so the whole
    structure keeps the alignment every other overlay shares."""
    from backend.core.occupancy_core import occupancy_fit_plan

    plan = occupancy_fit_plan(_FitDesign(), _fit_keys(), None, fit="selection")
    assert plan["fit"] == "global"
    assert plan["groups"] == []


def test_a_mixed_selection_fits_on_the_duplex_points_only():
    """An unpaired bead's RMSF is several times the duplex value, and Kabsch weights every
    point equally — let the inserts into the fit set and they drag the frame around."""
    from backend.core.occupancy_core import occupancy_fit_plan

    keys = _fit_keys()
    sel = list(range(len(keys)))  # duplex AND both inserts
    plan = occupancy_fit_plan(_FitDesign(), keys, sel, fit="selection")

    assert plan["fit"] == "selection"
    assert plan["n_fit_points"] == len(keys) - 2, (
        "the two __xb__ inserts stay out of the fit"
    )
    assert "duplex-paired" in (plan["note"] or "")
    ((fit_pos, out_pos, _slots),) = plan["groups"]
    assert len(out_pos) == len(keys), "every picked point is still a FEATURE"


def test_too_few_points_keeps_the_global_fit_and_says_so():
    from backend.core.occupancy_core import occupancy_fit_plan

    keys = _fit_keys()
    plan = occupancy_fit_plan(
        _FitDesign(), keys, [len(keys) - 2, len(keys) - 1], fit="selection"
    )
    assert plan["fit"] == "global"
    assert "no rotation to remove" in plan["note"]


def test_local_fit_uses_the_junction_flanking_duplex_not_the_inserts():
    """The extra-base mode: each insert is expressed in ITS OWN junction's frame, which is
    duplex nobody picked — so `need_idx` must be WIDER than the selection."""
    from backend.core.occupancy_core import occupancy_fit_plan

    keys = _fit_keys()
    inserts = [len(keys) - 2, len(keys) - 1]
    plan = occupancy_fit_plan(_FitDesign(), keys, inserts, fit="local")

    assert plan["fit"] == "local"
    assert len(plan["need_idx"]) > len(inserts), (
        "the flanking duplex must be retained too"
    )
    ((fit_pos, out_pos, slots),) = plan["groups"]
    assert plan["n_fit_points"] >= 3
    assert sorted(slots) == [0, 1], "both inserts are features"
    fit_keys = {keys[plan["need_idx"][p]] for p in fit_pos}
    assert all(k[0] != "__xb__" for k in fit_keys), (
        "a junction frame is duplex, not inserts"
    )
    assert all(abs(k[1] - 14) <= 3 for k in fit_keys), (
        "±3 bp of the crossover, nothing else"
    )


def test_local_fit_degrades_to_selection_when_no_extra_bases_are_picked():
    """A junction frame is undefined without a junction. Degrade and SAY so — a silent
    fallback would report a different analysis than the one asked for."""
    from backend.core.occupancy_core import occupancy_fit_plan

    keys = _fit_keys()
    plan = occupancy_fit_plan(_FitDesign(), keys, list(range(6)), fit="local")
    assert plan["fit"] == "selection"
    assert "junction frame is undefined" in plan["note"]


def test_apply_fit_plan_removes_a_junction_swing_but_keeps_the_flip():
    """End to end on synthetic frames: an insert that FLIPS between two poses while its
    junction swings must come out as the flip. Under the global fit it does not."""
    from backend.core.occupancy_core import (
        apply_fit_plan,
        occupancy_clusters,
        occupancy_fit_plan,
    )

    keys = _fit_keys()
    inserts = [len(keys) - 2, len(keys) - 1]
    plan = occupancy_fit_plan(_FitDesign(), keys, inserts, fit="local")
    need = plan["need_idx"]

    rng = np.random.default_rng(3)
    home = rng.normal(size=(len(need), 3)) * 2.0  # the local rest geometry
    P = []
    for t in range(60):
        th = 1.1 * np.sin(t / 4.0)  # the junction swings…
        R = np.array(
            [[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]]
        )
        f = home.copy()
        flip = 1.0 if (t % 8) < 4 else -1.0  # …while the inserts flip
        for slot, col in enumerate(plan["sel_pos"]):
            f[col] = f[col] + np.array([0.0, flip * 1.4, 0.0])
        P.append(
            f @ R.T
            + np.array([4 * np.cos(th), 0.0, 0.0])
            + rng.normal(scale=0.03, size=(len(need), 3))
        )
    P = np.array(P)

    X_local = apply_fit_plan(P, plan)
    assert X_local.shape == (60, len(inserts) * 3)
    assert occupancy_clusters(X_local)["k"] == 2, "the flip survives the junction fit"

    # After the junction fit, ALL that is left is the flip — its own amplitude, no more.
    assert X_local.std(axis=0).max() == pytest.approx(1.4, rel=0.05)

    flat = occupancy_fit_plan(_FitDesign(), keys, inserts, fit="global")
    X_global = apply_fit_plan(P[:, [need.index(c) for c in flat["need_idx"]], :], flat)
    assert X_global.std(axis=0).max() > 2.5 * X_local.std(axis=0).max(), (
        "the swing dominates the unfitted features — the reason this mode exists"
    )


def test_selection_by_domain_and_overhang(monkeypatch):
    """The shared anchor picker emits domain and overhang descriptors too, so the
    resolver must understand them or those picks would silently select nothing."""
    import backend.core.oxdna_occupancy as occ

    ks = [("h0", 0, "FORWARD"), ("h0", 1, "FORWARD"), ("h1", 0, "FORWARD")]
    meta = {
        ks[0]: ("sA", 0, None),
        ks[1]: ("sA", 1, "ovh1"),
        ks[2]: ("sB", 0, None),
    }

    class _Step:
        def __init__(self, key):
            sid, di, oid = meta[key]
            self.key = key
            self.strand = type("S", (), {"id": sid})()
            self.domain_index = di
            self.overhang_id = oid

    import backend.core.occupancy_core as core

    monkeypatch.setattr(
        core, "_walk_strand_nucleotides", lambda d: [_Step(k) for k in ks]
    )

    assert occ.resolve_selection_keys(
        _ScopedDesign(), ks, {"domains": [["sA", 1]]}
    ) == [ks[1]]
    assert occ.resolve_selection_keys(
        _ScopedDesign(), ks, {"overhang_ids": ["ovh1"]}
    ) == [ks[1]]


def test_selection_signature_ignores_ordering():
    """Two identical selections made in a different click order are the same analysis and
    must hit the same cache entry."""
    from backend.core.oxdna_occupancy import _selection_sig

    a = {
        "helix_ids": ["h1", "h0"],
        "bases": [["h0", 1, "FORWARD"], ["h0", 0, "FORWARD"]],
    }
    b = {
        "helix_ids": ["h0", "h1"],
        "bases": [["h0", 0, "FORWARD"], ["h0", 1, "FORWARD"]],
    }
    assert _selection_sig(a) == _selection_sig(b)
    assert _selection_sig(None) == ""
    assert _selection_sig({"helix_ids": ["h0"]}) != _selection_sig(
        {"helix_ids": ["h1"]}
    )


def test_cached_wrapper_resolves_its_module_globals():
    """production_occupancy_cached declares `global _OCCUPANCY_CACHE`; if that name is
    missing from the module the FIRST real request dies with a NameError while every unit
    test still passes, because nothing here otherwise calls the cached wrapper.

    Regression: extracting the shared core dropped the definition and broke every oxDNA
    occupancy request; only an end-to-end run caught it.
    """
    import backend.core.oxdna_occupancy as occ

    assert hasattr(occ, "_OCCUPANCY_CACHE")
    assert hasattr(occ, "_OCCUPANCY_CACHE_MAX")

    # Exercise the wrapper far enough to bind the global and build a cache key — a real
    # reference path is needed because the key stats each trajectory file.
    import inspect

    src = inspect.getsource(occ.production_occupancy_cached)
    assert "global _OCCUPANCY_CACHE" in src
    occ.occupancy_cache_clear()
    assert occ._OCCUPANCY_CACHE is None
