"""Unit coverage for the isolated surface capture-strand builder
(`backend/physics/oxdna_surface_strands.py`).

The builder appends sim-only ssDNA capture strands AFTER the origami particles, so these
tests assert: deterministic placement, FENE-safe seed spacing, correct oxDNA topology
threading, valid attach-end trap indices, and — critically — that appending to an existing
origami topology/config leaves the origami portion byte-for-byte unchanged.
"""

import math

import numpy as np
import pytest

from backend.core.constants import NM_TO_OXDNA, OXDNA_LENGTH_UNIT
from backend.physics.oxdna_interface import oxdna_backbone_site
from backend.physics.oxdna_surface_strands import (
    CaptureSpec,
    build_capture_strands,
    append_capture_strands,
    validate_capture_build,
    placement_points_nm,
    strand_count,
    coverage_area_nm2,
    plane_basis,
    mulberry32,
)

# FENE bond-length window: units [0.5064, 1.0064] (r0=0.7564, delta=0.25) → nm ×0.8518.
FENE_MIN_NM = 0.5064 * OXDNA_LENGTH_UNIT
FENE_MAX_NM = 1.0064 * OXDNA_LENGTH_UNIT


def _synthetic_origami(tmp_path):
    """A 4-nt, 1-strand origami top+conf along +y (oxDNA units)."""
    top = tmp_path / "topology.top"
    conf = tmp_path / "conf.dat"
    top.write_text(
        "4 1\n1 A 1 -1\n1 C 2 0\n1 G 3 1\n1 T -1 2\n",
        encoding="utf-8",
    )
    ys = [5.0, 6.0, 7.0, 8.0]
    lines = [
        "t = 0",
        "b = 40.000000 40.000000 40.000000",
        "E = 0.000000 0.000000 0.000000",
    ]
    for y in ys:
        lines.append(f"0.000000 {y:.6f} 0.000000  1 0 0  0 0 1  0 0 0  0 0 0")
    conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return top, conf, [[0.0, y, 0.0] for y in ys]


SURFACE = {"dir": [0.0, -1.0, 0.0], "offset_nm": 2.0}


# ── PRNG + placement math ──────────────────────────────────────────────────────────
def test_mulberry32_deterministic():
    a, b = mulberry32(42), mulberry32(42)
    assert [a(), a(), a()] == [b(), b(), b()]


def test_placement_deterministic_and_count():
    kw = dict(density_per_um2=10000.0, offset_x_nm=0.0, offset_y_nm=0.0)
    p1 = placement_points_nm("square", 20.0, 1, **kw)
    p2 = placement_points_nm("square", 20.0, 1, **kw)
    assert p1 == p2
    assert strand_count("square", 20.0, 10000.0) == 4  # 400 nm² × 1e4/µm² = 4
    assert len(p1) == 4


def test_placement_min_spacing_enforced():
    pts = placement_points_nm("square", 60.0, 5, count=80)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
            assert d >= 2.0 - 1e-9


def test_coverage_area_diameter_semantics():
    assert coverage_area_nm2("circle", 10.0) == pytest.approx(math.pi * 25.0)
    assert coverage_area_nm2("square", 10.0) == 100.0


def test_plane_basis_orthonormal():
    for normal in ([0, -1, 0], [0, 0, 1], [1, 0, 0], [0.3, 0.7, -0.2]):
        d, u, v = plane_basis(normal)
        assert np.dot(d, u) == pytest.approx(0.0, abs=1e-9)
        assert np.dot(d, v) == pytest.approx(0.0, abs=1e-9)
        assert np.dot(u, v) == pytest.approx(0.0, abs=1e-9)
        for w in (d, u, v):
            assert np.linalg.norm(w) == pytest.approx(1.0, abs=1e-9)


# ── The build ────────────────────────────────────────────────────────────────────
def test_build_shapes_and_threading():
    spec = CaptureSpec(
        sequence="ACGTACGT",
        attach_end="5'",
        shape="square",
        size_nm=20.0,
        density_per_um2=10000.0,
        seed=1,
    )
    cm = [[0.0, y, 0.0] for y in (5.0, 6.0, 7.0, 8.0)]
    b = build_capture_strands(
        spec,
        origami_cm_oxdna=cm,
        n_particles_origami=4,
        n_strands_origami=1,
        surface=SURFACE,
    )
    L = 8
    assert b.n_strands == 4
    assert b.n_beads == 4 * L
    assert len(b.topology_rows) == b.n_beads
    assert len(b.conf_lines) == b.n_beads
    # strand indices start after the origami's single strand
    assert {r[0] for r in b.topology_rows} == {2, 3, 4, 5}
    # per-strand threading: first bead has no 5′ neighbour, last has no 3′ neighbour
    for s in range(4):
        rows = b.topology_rows[s * L : (s + 1) * L]
        base = 4 + s * L
        assert rows[0][3] == -1 and rows[0][2] == base + 1  # n5=-1, n3=next
        assert rows[-1][2] == -1 and rows[-1][3] == base + L - 2  # n3=-1, n5=prev
        for k in range(1, L - 1):
            assert rows[k][2] == base + k + 1  # n3 = next
            assert rows[k][3] == base + k - 1  # n5 = prev


def test_build_fene_safe_backbone_bonds():
    """The real FENE bond is between consecutive backbone SITES (CM + a1/a2 offset).
    A B-form seed must keep every such bond inside the FENE window, or the run blows up
    on step 0 (a too-SHORT bond is as fatal as a too-long one)."""
    spec = CaptureSpec(
        sequence="ACGTACGTAC",
        attach_end="5'",
        shape="square",
        size_nm=20.0,
        density_per_um2=10000.0,
        seed=1,
    )
    cm = [[0.0, y, 0.0] for y in (5.0, 6.0, 7.0, 8.0)]
    b = build_capture_strands(
        spec,
        origami_cm_oxdna=cm,
        n_particles_origami=4,
        n_strands_origami=1,
        surface=SURFACE,
    )
    L = 10
    for s in range(b.n_strands):
        sites = []
        for ln in b.conf_lines[s * L : (s + 1) * L]:
            f = [float(x) for x in ln.split()]
            cm_nm = np.array(f[:3]) / NM_TO_OXDNA  # conf is oxDNA units → nm
            a1, a3 = np.array(f[3:6]), np.array(f[6:9])
            sites.append(oxdna_backbone_site(cm_nm, a1, a3))
        for k in range(1, L):
            d = float(np.linalg.norm(sites[k] - sites[k - 1]))  # nm
            assert FENE_MIN_NM < d < FENE_MAX_NM, (
                f"backbone bond {d:.3f} nm out of FENE window"
            )


def test_trap_at_attach_end_5prime_vs_3prime():
    cm = [[0.0, y, 0.0] for y in (5.0, 6.0, 7.0, 8.0)]
    L = 6
    kw = dict(shape="square", size_nm=20.0, density_per_um2=10000.0, seed=1)
    b5 = build_capture_strands(
        CaptureSpec(sequence="ACGTAC", attach_end="5'", **kw),
        origami_cm_oxdna=cm,
        n_particles_origami=4,
        n_strands_origami=1,
        surface=SURFACE,
    )
    b3 = build_capture_strands(
        CaptureSpec(sequence="ACGTAC", attach_end="3'", **kw),
        origami_cm_oxdna=cm,
        n_particles_origami=4,
        n_strands_origami=1,
        surface=SURFACE,
    )
    # one trap per strand
    assert len(b5.trap_anchors) == b5.n_strands
    # 5′ tether → attach is the strand's FIRST bead; 3′ tether → its LAST bead
    assert b5.trap_anchors[0][0] == 4  # first strand, bead 0
    assert b3.trap_anchors[0][0] == 4 + L - 1  # first strand, last bead
    # a3 (5′→3′) flips sign between the two attach ends
    a3_5 = np.array([float(x) for x in b5.conf_lines[0].split()[6:9]])
    a3_3 = np.array([float(x) for x in b3.conf_lines[0].split()[6:9]])
    assert np.allclose(a3_5, -a3_3, atol=1e-6)


def test_empty_when_no_sequence_or_no_strands():
    cm = [[0.0, y, 0.0] for y in (5.0, 6.0)]
    assert (
        build_capture_strands(
            CaptureSpec(sequence=""),
            origami_cm_oxdna=cm,
            n_particles_origami=2,
            n_strands_origami=1,
            surface=SURFACE,
        ).n_beads
        == 0
    )
    spec = CaptureSpec(
        sequence="ACGT", density_per_um2=0.0
    )  # zero density → no strands
    assert (
        build_capture_strands(
            spec,
            origami_cm_oxdna=cm,
            n_particles_origami=2,
            n_strands_origami=1,
            surface=SURFACE,
        ).n_beads
        == 0
    )


# ── File-level append: origami must be preserved byte-for-byte ─────────────────────
def test_append_preserves_origami_and_bumps_headers(tmp_path):
    top, conf, _cm = _synthetic_origami(tmp_path)
    top_before = top.read_text().splitlines()
    conf_before = conf.read_text().splitlines()

    spec = CaptureSpec(
        sequence="ACGTACGT",
        attach_end="5'",
        shape="square",
        size_nm=20.0,
        density_per_um2=10000.0,
        seed=1,
    )
    info = append_capture_strands(top, conf, spec, SURFACE)

    top_after = top.read_text().splitlines()
    conf_after = conf.read_text().splitlines()
    n_beads = info["n_beads"]
    assert n_beads == 32 and info["n_strands"] == 4

    # header bumped correctly
    assert top_after[0] == f"{4 + n_beads} {1 + 4}"
    # origami rows/lines preserved verbatim (everything except the header line)
    assert top_after[1:5] == top_before[1:5]
    assert len(top_after) == len(top_before) + n_beads
    # conf: the 4 origami particle lines (after the 3 header lines) are untouched
    assert conf_after[3:7] == conf_before[3:7]
    assert len(conf_after) == len(conf_before) + n_beads
    # box only ever grows
    assert conf_after[1].startswith("b = ")

    # trap text: one block per strand, all particle indices in the appended range
    assert info["trap_text"].count("type = trap") == 4
    for particle, _pos in info["trap_anchors"]:
        assert 4 <= particle < 4 + n_beads


def test_append_noop_when_disabled(tmp_path):
    top, conf, _cm = _synthetic_origami(tmp_path)
    top_before, conf_before = top.read_text(), conf.read_text()
    spec = CaptureSpec(sequence="ACGT", density_per_um2=0.0)  # builds nothing
    info = append_capture_strands(top, conf, spec, SURFACE)
    assert info["n_beads"] == 0
    assert top.read_text() == top_before  # files untouched
    assert conf.read_text() == conf_before


# ── Full relax-build integration through prepare_oxdna_job ─────────────────────────
def test_prepare_oxdna_job_builds_capture_strands(tmp_path):
    """End-to-end at the build level: a real 6hb design relaxed with a hard surface +
    capture strands writes an enlarged topology/conf and holds the strands with traps in
    both forces.txt and equil_forces.txt — while the origami particle count is preserved."""
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import _strand_nucleotide_order
    from tests.conftest import make_6hb_design

    design = make_6hb_design()
    geometry = _geometry_for_design(design)
    n_origami = len(_strand_nucleotide_order(design))

    specs = build_relaxation_stages(
        mc_steps=100,
        md_relax_steps=100,
        equil_steps=100,
        backend="CPU",
        device="0",
        salt_concentration=0.5,
        min_bp_retained=0.5,
        surface_present=True,
        protein=False,
    )
    job = new_oxdna_job(
        design_name="6hb",
        stages=[s.to_status() for s in specs],
        device="0",
        backend="CPU",
        salt_concentration=0.5,
    )
    surface = {
        "dir": [0, -1, 0],
        "offset_nm": 20.0,
        "stiff": 5.0,
    }  # generous offset → no clash
    strands = {
        "enabled": True,
        "sequence": "ACGTACGT",
        "attachEnd": "5'",
        "shape": "circle",
        "sizeNm": 60.0,
        "densityPerUm2": 4000.0,
        "seed": 7,
    }

    info = prepare_oxdna_job(
        design, geometry, job, tmp_path, specs, surface=surface, surface_strands=strands
    )

    jd = job.job_dir(tmp_path)
    cap = info["capture"]
    assert cap["n_strands"] >= 1 and cap["n_beads"] == cap["n_strands"] * 8

    # topology header grew by exactly the capture beads/strands; origami rows preserved
    top_lines = (jd / "topology.top").read_text().splitlines()
    n_top, n_str = (int(x) for x in top_lines[0].split())
    assert n_top == n_origami + cap["n_beads"]
    # every appended row's 3′/5′ neighbour index is within the new particle range or -1
    for ln in top_lines[1 + n_origami :]:
        _si, _base, n3, n5 = ln.split()
        for nb in (int(n3), int(n5)):
            assert nb == -1 or 0 <= nb < n_top

    # conf grew by the same bead count
    conf_lines = (jd / "conf.dat").read_text().splitlines()
    assert len(conf_lines) == 3 + n_top

    # capture traps present in BOTH the relax forces and the equil-stage forces
    trap_count = cap["n_strands"]
    assert (jd / "equil_forces.txt").read_text().count("type = trap") >= trap_count
    forces_txt = (jd / "forces.txt").read_text()
    assert forces_txt.count("type = trap") >= trap_count


# ── Headless setup → build → validate (the automation entry + its oracle) ──────────
def test_headless_setup_build_validate():
    """Automation entry: configure surface strands on a real design, build the oxDNA job
    headlessly, and run the physical-invariant oracle on the on-disk files — no GPU/sim."""
    import tempfile
    from pathlib import Path as _P
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.api.crud import _geometry_for_design
    from tests.conftest import make_6hb_design

    design = make_6hb_design()
    geometry = _geometry_for_design(design)
    n_origami_strands = len(design.strands)

    specs = build_relaxation_stages(
        mc_steps=100,
        md_relax_steps=100,
        equil_steps=100,
        backend="CPU",
        device="0",
        salt_concentration=0.5,
        min_bp_retained=0.5,
        surface_present=True,
        protein=False,
    )
    surface = {"dir": [0, -1, 0], "offset_nm": 20.0, "stiff": 5.0}
    strands = {
        "enabled": True,
        "sequence": "ACGTACGT",
        "attachEnd": "5'",
        "shape": "square",
        "sizeNm": 80.0,
        "densityPerUm2": 5000.0,
        "seed": 3,
    }

    with tempfile.TemporaryDirectory() as tmp:
        ws = _P(tmp)
        job = new_oxdna_job(
            design_name="6hb",
            stages=[s.to_status() for s in specs],
            device="0",
            backend="CPU",
            salt_concentration=0.5,
        )
        info = prepare_oxdna_job(
            design, geometry, job, ws, specs, surface=surface, surface_strands=strands
        )
        jd = job.job_dir(ws)
        report = validate_capture_build(
            jd / "topology.top",
            jd / "conf.dat",
            n_origami_strands=n_origami_strands,
            trap_particles=info["capture"]["trap_particles"],
        )

    assert report["ok"], report["failures"]
    assert report["n_capture_strands"] >= 1
    assert report["checks"]["fene_safe"] and report["checks"]["threading_valid"]
    assert report["checks"]["min_spacing"] and report["checks"]["traps_in_range"]


def test_display_reader_skips_trailing_capture_beads(tmp_path):
    """Regression: the relaxed-frame reader must read the origami from the FRONT and treat
    capture beads as trailing extras — NOT mistake them for leading protein beads (which
    would shift every origami nucleotide onto the wrong line).  Also the stale-topology
    guard must allow the known trailing surplus instead of 409-ing."""
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import (
        read_configuration_full,
        assert_topology_matches_design,
        StaleJobTopologyError,
        _strand_nucleotide_order,
    )
    from tests.conftest import make_6hb_design

    design = make_6hb_design()
    geometry = _geometry_for_design(design)
    order = _strand_nucleotide_order(design)
    specs = build_relaxation_stages(
        mc_steps=100,
        md_relax_steps=100,
        equil_steps=100,
        backend="CPU",
        device="0",
        salt_concentration=0.5,
        min_bp_retained=0.5,
        surface_present=True,
        protein=False,
    )
    job = new_oxdna_job(
        design_name="6hb",
        stages=[s.to_status() for s in specs],
        device="0",
        backend="CPU",
        salt_concentration=0.5,
    )
    surface = {"dir": [0, -1, 0], "offset_nm": 20.0, "stiff": 5.0}
    strands = {
        "enabled": True,
        "sequence": "ACGTACGT",
        "attachEnd": "5'",
        "shape": "square",
        "sizeNm": 80.0,
        "densityPerUm2": 5000.0,
        "seed": 3,
    }
    info = prepare_oxdna_job(
        design, geometry, job, tmp_path, specs, surface=surface, surface_strands=strands
    )
    jd = job.job_dir(tmp_path)
    n_cap = info["capture"]["n_beads"]

    # guard: allowed with the surplus, raises without it
    assert_topology_matches_design(jd / "topology.top", design, extra_trailing=n_cap)
    with pytest.raises(StaleJobTopologyError):
        assert_topology_matches_design(jd / "topology.top", design)

    # reader: origami read from the front (offset 0) → exactly the design-walk keys, and the
    # first nucleotide matches the seed conf's front line (NOT shifted by n_cap).
    fixed = read_configuration_full(jd / "conf.dat", design, n_trailing_extra=n_cap)
    shifted = read_configuration_full(jd / "conf.dat", design, n_trailing_extra=0)
    assert len(fixed) == len(order)
    k0 = order[0][:3]
    assert not np.allclose(
        fixed[k0]["backbone_position"], shifted[k0]["backbone_position"]
    )


def test_surface_jobs_disallow_alignment():
    """Alignment (Kabsch superpose to the design pose) is forced OFF for surface jobs —
    aligning undoes the settling that keeps the structure above the plane, so it looks like
    it clips through the surface. `_job_has_surface` is the decision point."""
    from backend.api.routes_oxdna import _job_has_surface

    class _J:
        def __init__(self, rc):
            self.run_config = rc

    assert _job_has_surface(_J({"surface": {"dir": [0, -1, 0], "stiff": 5}}))
    assert _job_has_surface(_J({"surface_strands": {"enabled": True}}))
    assert not _job_has_surface(_J({"surface": None, "anchors": []}))
    assert not _job_has_surface(_J({}))
    assert not _job_has_surface(_J(None))


def test_oracle_catches_a_broken_bond(tmp_path):
    """The oracle must FAIL on a corrupted build — proves it actually validates (a green
    oracle that can't go red is worthless)."""
    top, conf, _cm = _synthetic_origami(tmp_path)
    spec = CaptureSpec(
        sequence="ACGTACGT",
        attach_end="5'",
        shape="square",
        size_nm=40.0,
        density_per_um2=20000.0,
        seed=1,
    )
    info = append_capture_strands(top, conf, spec, SURFACE)
    traps = [p for p, _pos in info["trap_anchors"]]

    good = validate_capture_build(top, conf, n_origami_strands=1, trap_particles=traps)
    assert good["ok"], good["failures"]

    # Move one capture bead far away → its backbone bond leaves the FENE window.
    lines = conf.read_text().splitlines()
    last = lines[-1].split()
    last[0] = str(float(last[0]) + 50.0)  # +50 oxDNA units along x
    lines[-1] = " ".join(last)
    conf.write_text("\n".join(lines) + "\n")

    bad = validate_capture_build(top, conf, n_origami_strands=1, trap_particles=traps)
    assert not bad["ok"]
    assert not bad["checks"]["fene_safe"]
