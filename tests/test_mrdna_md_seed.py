"""mrDNA job → GROMACS MD-seed route: gating + wiring validation.

Covers the ``/design/export/gromacs-mrdna-start`` path that seeds a GROMACS
package from a COMPLETED fine-stage mrDNA job (sibling of the oxDNA
``gromacs-cg-start``).  The route is thin wiring over two runner helpers:

  - ``resolve_md_seed_inputs`` — gates the job (completed + fine + files present)
    and returns ``(snapshot_design, psf, dcd)``.  Pure Python, no GPU/mrdna — the
    bulk of the validation lives here (fast, deterministic).
  - ``build_md_seed_override`` — runs the real Phase-3b spline extraction; needs
    mrdna + MDAnalysis + a real fine-stage job, so it is exercised only by the
    skip-guarded integration test against an on-disk job fixture.

The heavy end-to-end (real ARBD fine run → override → GROMACS EM step reduction)
is hardware/GPU-bound and tracked as manual-validation debt, not asserted here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.mrdna_job import MrdnaStatus, new_mrdna_job
from backend.core.mrdna_runner import resolve_md_seed_inputs
from tests.conftest import make_minimal_design

_CG_PSF_BYTES = b"PSF\n\n       2 !NATOM\n"  # not parsed here; _psf_is_cg only greps b"DNA"


def _completed_fine_job(ws: Path, *, fine_steps: int = 1000):
    """A completed, fine-stage mrDNA job persisted in ``ws`` (no sim output yet)."""
    job = new_mrdna_job("seedtest", fine_steps=fine_steps, n_nucleotides=84)
    job.status = MrdnaStatus.completed
    for st in job.stages:
        st.status = "done"
    job.save(ws)
    return job


def _write_snapshot(job, ws: Path) -> None:
    (job.job_dir(ws) / "design.json").write_text(
        make_minimal_design(n_helices=2).model_dump_json()
    )


def _write_fine_stage(job, ws: Path) -> tuple[Path, Path]:
    """Fabricate the on-disk fine-stage files ``_sim_paths`` looks for: a numbered
    CG PSF (contains ``DNA`` so ``_psf_is_cg`` is true) + its DCD.  Returns the
    ``(psf, dcd)`` paths ``resolve_md_seed_inputs`` should hand back."""
    jd = job.job_dir(ws)
    (jd / "output").mkdir(parents=True, exist_ok=True)
    psf = jd / "mrdna_relax-2.psf"
    dcd = jd / "output" / "mrdna_relax-2.dcd"
    psf.write_bytes(_CG_PSF_BYTES + b"DNA\n")
    dcd.write_bytes(b"")  # existence is all _sim_paths checks
    return psf, dcd


# ── Gating: resolve_md_seed_inputs (fast, no mrdna) ──────────────────────────


def test_rejects_non_completed_job(tmp_path):
    job = _completed_fine_job(tmp_path)
    job.status = MrdnaStatus.running
    with pytest.raises(ValueError, match="only a completed job"):
        resolve_md_seed_inputs(job, tmp_path)


def test_rejects_coarse_only_job(tmp_path):
    job = _completed_fine_job(tmp_path, fine_steps=0)
    _write_snapshot(job, tmp_path)
    with pytest.raises(ValueError, match="coarse-only"):
        resolve_md_seed_inputs(job, tmp_path)


def test_rejects_missing_snapshot(tmp_path):
    job = _completed_fine_job(tmp_path)
    # no design.json written
    with pytest.raises(ValueError, match="snapshot"):
        resolve_md_seed_inputs(job, tmp_path)


def test_rejects_missing_fine_output(tmp_path):
    job = _completed_fine_job(tmp_path)
    _write_snapshot(job, tmp_path)
    # snapshot present but no numbered fine PSF/DCD → _sim_paths falls back to the
    # coarse single-stage name (no dash) → rejected.
    with pytest.raises(ValueError, match="no fine-stage output"):
        resolve_md_seed_inputs(job, tmp_path)


def test_passes_and_returns_fine_inputs(tmp_path):
    job = _completed_fine_job(tmp_path)
    _write_snapshot(job, tmp_path)
    psf, dcd = _write_fine_stage(job, tmp_path)

    design, got_psf, got_dcd = resolve_md_seed_inputs(job, tmp_path)

    assert got_psf == psf and got_dcd == dcd
    assert len(design.helices) == 2  # the snapshot, not the live design


# ── Route wiring: gating surfaces as HTTP status codes ───────────────────────


def _client():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app)


def test_route_unknown_job_404():
    r = _client().post("/api/design/export/gromacs-mrdna-start",
                       params={"mrdna_job_id": "does-not-exist"})
    assert r.status_code == 404


def test_route_coarse_only_409(tmp_path, monkeypatch):
    # Point the route's workspace at a temp dir holding one coarse-only job.
    import backend.api.assembly as assembly
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    job = _completed_fine_job(tmp_path, fine_steps=0)
    _write_snapshot(job, tmp_path)

    r = _client().post("/api/design/export/gromacs-mrdna-start",
                       params={"mrdna_job_id": job.job_id})
    assert r.status_code == 409
    assert "coarse-only" in r.json()["detail"]


# ── NAMD seed precheck (gating mirror; raises FileNotFoundError for the MD route) ─


def test_namd_seed_precheck_rejects_unknown_job(tmp_path):
    from backend.core.mrdna_runner import assert_mrdna_namd_seed_available
    with pytest.raises(FileNotFoundError):
        assert_mrdna_namd_seed_available("nope", tmp_path)


def test_namd_seed_precheck_rejects_coarse_only(tmp_path):
    from backend.core.mrdna_runner import assert_mrdna_namd_seed_available
    job = _completed_fine_job(tmp_path, fine_steps=0)
    _write_snapshot(job, tmp_path)
    with pytest.raises(FileNotFoundError, match="coarse-only"):
        assert_mrdna_namd_seed_available(job.job_id, tmp_path)


def test_namd_seed_precheck_passes_with_fine_fixture(tmp_path):
    from backend.core.mrdna_runner import assert_mrdna_namd_seed_available
    job = _completed_fine_job(tmp_path)
    _write_snapshot(job, tmp_path)
    _write_fine_stage(job, tmp_path)
    assert_mrdna_namd_seed_available(job.job_id, tmp_path)  # no raise


# ── ssDNA / overhang run enumeration (pure topology, no GPU) ─────────────────

_WS = Path(__file__).resolve().parent.parent / "workspace"
_OH_DESIGN = _WS / "OH6hb_test.nadoc"


def _load_oh_design():
    if not _OH_DESIGN.exists():
        pytest.skip("workspace/OH6hb_test.nadoc (overhang fixture) not present")
    raw = json.loads(_OH_DESIGN.read_text())
    from backend.core.models import Design
    return Design.model_validate(raw.get("design", raw))


def test_ssdna_runs_finds_unpaired_runs_with_paired_roots():
    """_ssdna_runs must surface every contiguous unpaired run, and each run's root
    must be a genuinely PAIRED nucleotide (the anchor the seed re-attaches to)."""
    import numpy as np
    from backend.core.mrdna_bridge import _ssdna_runs, _build_nt_arrays

    design = _load_oh_design()
    _r, bp, _s, _tp, _o, _seq, nt_key = _build_nt_arrays(design, return_nt_key=True)
    key_to_idx = {(h, b, d): i for (h, b, d, k), i in nt_key.items() if k == 0}

    runs = _ssdna_runs(design)
    assert runs, "overhang design should have ≥1 ss run"
    for run in runs:
        assert run["keys"], "run must be non-empty"
        # every run nucleotide is unpaired
        for key in run["keys"]:
            assert bp[key_to_idx[key]] < 0, f"{key} in ss run but is paired"
        # the root (if any) is paired and NOT itself in the run
        if run["root_key"] is not None:
            assert bp[key_to_idx[run["root_key"]]] >= 0, "root must be paired"
            assert run["root_key"] not in set(run["keys"])
            assert run["root_side"] in ("5p", "3p")
        assert len(run["ideal_nm"]) == len(run["keys"])


# ── Integration: real override from an on-disk fine-stage job (skip-guarded) ──


def _find_completed_fine_job() -> "tuple | None":
    """First on-disk completed fine-stage mrDNA job with a snapshot + fine files."""
    jobs_dir = _WS / "mrdna_jobs"
    if not jobs_dir.exists():
        return None
    from backend.core.mrdna_job import MrdnaJob
    for jdir in sorted(jobs_dir.iterdir()):
        if not (jdir / "job.json").exists():
            continue
        try:
            job = MrdnaJob.load(jdir.name, _WS)
        except Exception:
            continue
        if job.status != MrdnaStatus.completed or job.fine_steps <= 0:
            continue
        try:
            return resolve_md_seed_inputs(job, _WS)
        except ValueError:
            continue
    return None


@pytest.mark.slow
def test_build_md_seed_override_on_real_job():
    pytest.importorskip("MDAnalysis")
    from backend.core.mrdna_bridge import find_mrdna
    if not find_mrdna():
        pytest.skip("mrdna not installed")
    inputs = _find_completed_fine_job()
    if inputs is None:
        pytest.skip("no completed fine-stage mrDNA job in workspace/mrdna_jobs")

    from backend.core.mrdna_runner import build_md_seed_override
    from backend.core.mrdna_bridge import _crossover_junction_keys, _ssdna_runs
    design, psf, dcd = inputs
    override = build_md_seed_override(design, psf, dcd)

    assert override, "override should be non-empty"
    import numpy as np
    from collections import Counter
    vals = np.array(list(override.values()))
    assert not np.isnan(vals).any() and not np.isinf(vals).any()
    # Crossover keys are INCLUDED (the whole point vs the coarse/display override).
    xkeys = _crossover_junction_keys(design)
    if xkeys:
        assert xkeys & set(override), "crossover nucleotides must be in the seed override"
    # No two nucleotides share a position — coincident atoms are the LJ=2e37 failure
    # (this is what the ss junction re-anchor guards against; regression pin).
    dups = [c for _, c in Counter(tuple(np.round(v, 4)) for v in override.values()).items() if c > 1]
    assert not dups, f"{len(dups)} coincident override positions (LJ=2e37 risk)"
    # ss/overhang nts are either re-seeded OR deliberately left at ideal by the
    # do-no-harm selector; the ones that ARE re-seeded must carry their run's root.
    ss_keys = {k for run in _ssdna_runs(design) for k in run["keys"] if k is not None}
    assert set(override) & ss_keys or all(
        r["root_key"] is None for r in _ssdna_runs(design)), \
        "no ss nt re-seeded despite anchored runs (selector never chose spline/translate)"


def _junction_gap_and_clash(design, override):
    """(min ss/ds junction backbone P–P gap, min ss→non-root-body atom dist), nm —
    the seed-quality oracle: the junction gap should sit near a backbone bond
    (~0.7 nm) not a broken 1.4 nm jump, and the clash must stay above VDW contact."""
    import numpy as np
    from scipy.spatial import cKDTree
    from backend.core.atomistic import build_atomistic_model
    from backend.core.mrdna_bridge import _ssdna_runs

    runs = _ssdna_runs(design)
    ss_keys = {k for run in runs for k in run["keys"] if k is not None}
    root_keys = {run["root_key"] for run in runs if run["root_key"]}

    def _key(a):
        return (a.helix_id, a.bp_index,
                a.direction if isinstance(a.direction, str) else a.direction.value)

    m = build_atomistic_model(design, nuc_pos_override=override)
    ss_xyz, far_xyz, root_p, adj_p = [], [], {}, []
    for a in m.atoms:
        # Crossover extra-base inserts are flexible junction ssDNA, not overhangs
        # nor rigid body — and they now (correctly) share their source flank's
        # (helix, bp, dir) key, so they'd pollute the ss/root/body buckets.  Excluded.
        if getattr(a, "crossover_id", None) is not None:
            continue
        k, p = _key(a), [a.x, a.y, a.z]
        if k in ss_keys:
            ss_xyz.append(p)
            if a.name == "P":
                adj_p.append((k, p))
        elif k in root_keys:
            if a.name == "P":
                root_p[k] = p
        else:
            far_xyz.append(p)
    clash = float(cKDTree(np.array(far_xyz)).query(np.array(ss_xyz))[0].min())
    gaps = []
    for run in runs:
        rk = run["root_key"]
        if rk in root_p:
            adj = run["keys"][-1] if run["root_side"] == "3p" else run["keys"][0]
            for k, p in adj_p:
                if k == adj:
                    gaps.append(float(np.linalg.norm(np.array(p) - np.array(root_p[rk]))))
    return (min(gaps) if gaps else float("nan")), clash


def _bp_vector_rotation_per_helix(design, override):
    """Median rotation (deg) of the FORWARD→REVERSE base-pair vector between
    consecutive base pairs, per helix — the axis-independent measure of helical
    twist.  ~34 deg/bp is B-DNA; a near-zero value means the duplex was reconstructed
    as an untwisted ladder.  Uses the base-pair vector (not the backbone azimuth
    around some reference axis) so a bent/tilted relaxed axis does not confound it."""
    import numpy as np
    from collections import defaultdict

    by_h: dict = defaultdict(dict)
    for (h_id, bp, d), pos in override.items():
        by_h[h_id][(bp, d)] = np.asarray(pos, dtype=float)

    out: dict = {}
    for h_id, m in by_h.items():
        bps = sorted({bp for bp, _ in m})
        rot, prev = [], None
        for bp in bps:
            if (bp, "FORWARD") in m and (bp, "REVERSE") in m:
                v = m[(bp, "FORWARD")] - m[(bp, "REVERSE")]
                if prev is not None and prev[0] == bp - 1:
                    a, b = prev[1], v
                    c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
                    rot.append(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))
                prev = (bp, v)
        if rot:
            out[h_id] = float(np.median(rot))
    return out


@pytest.mark.slow
def test_seed_reconstruction_has_bdna_twist():
    """REGRESSION: the mrDNA fine-stage 'DNA' bead is an axis/centroid bead — the
    ~34 deg/bp helical twist lives in the separate ORIENTATION bead, which the seed
    override never reads.  Deriving the backbone azimuth from the DNA-bead radial
    (the old code) read the helix's rigid lateral relaxation offset as twist phase
    and produced a near-zero-twist ladder (measured ~1 deg/bp), so every mrDNA-seeded
    NAMD run relaxed to a non-helical arrangement.  The fix imposes IDEAL B-DNA twist
    around the relaxed axis; the reconstructed duplex must rotate ~34 deg/bp again."""
    pytest.importorskip("MDAnalysis")
    from backend.core.mrdna_bridge import find_mrdna, nuc_pos_override_from_arbd_strands
    if not find_mrdna():
        pytest.skip("mrdna not installed")
    inputs = _find_completed_fine_job()
    if inputs is None:
        pytest.skip("no completed fine-stage mrDNA job in workspace/mrdna_jobs")
    design, psf, dcd = inputs

    override = nuc_pos_override_from_arbd_strands(design, str(psf), str(dcd))
    twist = _bp_vector_rotation_per_helix(design, override)
    assert twist, "no dsDNA helices reconstructed"
    # Every ds helix must show a genuine helical twist near B-DNA (34.3 deg/bp).  The
    # old ladder bug sat at ~1 deg/bp for all helices; the band comfortably separates
    # the two while tolerating relaxed-axis wobble.
    for h_id, deg in twist.items():
        assert 28.0 <= deg <= 40.0, (
            f"helix {h_id} reconstructed with {deg:.1f} deg/bp twist "
            f"(B-DNA ~34.3; near-zero = the untwisted-ladder regression)")


@pytest.mark.slow
def test_ssdna_seed_restores_junction_and_does_no_harm():
    """ssDNA/overhang handling must (a) restore backbone continuity at any ss/ds
    junction a dsDNA-only override leaves BROKEN, and (b) not push an overhang closer
    to the body than the ideal (ds-only) placement already had — the do-no-harm
    guarantee.  It cannot promise a clash-free overhang on dense bundles where the
    ds-only baseline ALREADY clashes (long overhang through a bundle core is a
    separate geometry problem), so the clash assertion is relative, not absolute."""
    pytest.importorskip("MDAnalysis")
    pytest.importorskip("scipy")
    from backend.core.mrdna_bridge import (
        find_mrdna, _ssdna_runs,
        nuc_pos_override_from_arbd_strands, nuc_pos_override_ssdna_from_arbd,
    )
    if not find_mrdna():
        pytest.skip("mrdna not installed")
    inputs = _find_completed_fine_job()
    if inputs is None:
        pytest.skip("no completed fine-stage mrDNA job in workspace/mrdna_jobs")
    design, psf, dcd = inputs
    if not any(r["root_key"] for r in _ssdna_runs(design)):
        pytest.skip("job's design has no anchored ss/overhang runs")

    ds = nuc_pos_override_from_arbd_strands(design, str(psf), str(dcd))
    ss = nuc_pos_override_ssdna_from_arbd(design, str(psf), str(dcd), ds)

    gap_ds, clash_ds  = _junction_gap_and_clash(design, ds)             # ss detached
    gap_all, clash_all = _junction_gap_and_clash(design, {**ds, **ss})  # ss handled

    # (a) a broken junction (gap ≫ a backbone bond) must be restored.
    if gap_ds > 1.0:
        assert gap_all < gap_ds and gap_all < 1.1, (
            f"broken ss/ds junction not restored (ds-only {gap_ds:.2f} → "
            f"ds+ss {gap_all:.2f} nm)")
    # (b) do no harm: never push ss meaningfully closer to the body than ideal
    # (0.03 nm tolerance for the coarse ds-backbone clash proxy vs full atomistic).
    # Skip when the ds-only baseline ALREADY clashes below VDW contact: that is the
    # dense-bundle regime the docstring carves out (long overhang threading a bundle
    # core clashes under any placement — 6hb_2xT's overhangs do), where there is no
    # clearance left to preserve and the relative guarantee is meaningless.
    _VDW_CONTACT_NM = 0.25
    if clash_ds >= _VDW_CONTACT_NM:
        assert clash_all >= clash_ds - 0.03, (
            f"ss handling worsened the body clearance (ds-only {clash_ds:.3f} → "
            f"ds+ss {clash_all:.3f} nm)")


@pytest.mark.slow
def test_build_namd_seed_from_mrdna_on_real_job():
    """The NAMD-seed builder reconstructs a recentered atomistic model from a real
    fine-stage mrDNA job (the sibling of oxDNA's build_namd_seed)."""
    pytest.importorskip("MDAnalysis")
    from backend.core.mrdna_bridge import find_mrdna
    if not find_mrdna():
        pytest.skip("mrdna not installed")
    jobs_dir = _WS / "mrdna_jobs"
    if not jobs_dir.exists():
        pytest.skip("no workspace/mrdna_jobs")
    from backend.core.mrdna_job import MrdnaJob
    from backend.core.mrdna_runner import build_namd_seed_from_mrdna
    import numpy as np

    for jdir in sorted(jobs_dir.iterdir()):
        if not (jdir / "job.json").exists():
            continue
        try:
            job = MrdnaJob.load(jdir.name, _WS)
        except Exception:
            continue
        if job.status != MrdnaStatus.completed or job.fine_steps <= 0:
            continue
        seed = build_namd_seed_from_mrdna(job.job_id, _WS)
        assert seed.atomistic_model.atoms, "seed model must have atoms"
        assert seed.source_job_id == job.job_id
        # recentered on the origin (else the PDB's 8-char coord fields overflow)
        c = np.mean([[a.x, a.y, a.z] for a in seed.atomistic_model.atoms], axis=0)
        assert np.linalg.norm(c) < 1e-3, f"seed model not recentered (centroid {c})"
        return
    pytest.skip("no completed fine-stage mrDNA job in workspace/mrdna_jobs")
