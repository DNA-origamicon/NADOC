"""Tests for the oxDNA → LAMMPS (CG-DNA) transcoder (backend/physics/lammps_interface).

Pure — no LAMMPS binary needed.  The critical piece, ``exyz_to_quat`` (ported
verbatim from the LAMMPS CG-DNA reference generator), is checked by round-tripping:
its quaternion must encode the (a1, a2, a3) body frame as the *columns* of the
rotation matrix (LAMMPS's convention).  A real end-to-end LAMMPS run of transcoder
output lives in test_lammps_runner.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.physics import lammps_interface as L

# A minimal 2-bp duplex: strands (0,1) and (2,3); each strand's nt0 bonds 3′→nt1.
_TOP = """4 2
1 A 1 -1
1 T -1 0
2 A 3 -1
2 T -1 2
"""
_CONF = """t = 0
b = 30 30 30
E = 0 0 0
0 0 0      1 0 0   0 0 1   0 0 0 0 0 0
0.7 0 0   -1 0 0   0 0 1   0 0 0 0 0 0
0 0 0.4    1 0 0   0 0 1   0 0 0 0 0 0
0.7 0 0.4 -1 0 0   0 0 1   0 0 0 0 0 0
"""


def _quat_to_matrix(q):
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


# ── exyz_to_quat (the ported body-frame → quaternion) ─────────────────────────


def test_exyz_to_quat_encodes_frame_as_matrix_columns():
    """For 500 random right-handed frames, the quaternion's rotation matrix must
    have a1, a2=a3×a1, a3 as its COLUMNS (to machine precision)."""
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(500):
        a3 = rng.standard_normal(3)
        a3 /= np.linalg.norm(a3)
        t = rng.standard_normal(3)
        a1 = t - a3 * np.dot(a3, t)
        a1 /= np.linalg.norm(a1)
        a2 = np.cross(a3, a1)
        R = _quat_to_matrix(L.exyz_to_quat(a1, a3))
        worst = max(
            worst,
            np.abs(R[:, 0] - a1).max(),
            np.abs(R[:, 1] - a2).max(),
            np.abs(R[:, 2] - a3).max(),
        )
    assert worst < 1e-9


def test_exyz_to_quat_is_unit_norm():
    q = L.exyz_to_quat([0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
    assert abs(np.linalg.norm(q) - 1.0) < 1e-12


def test_quat_to_exyz_inverts_exyz_to_quat():
    """Trajectory read-back: quat_to_exyz must recover the (a1, a3) exyz_to_quat encoded."""
    rng = np.random.default_rng(1)
    worst = 0.0
    for _ in range(500):
        a3 = rng.standard_normal(3)
        a3 /= np.linalg.norm(a3)
        t = rng.standard_normal(3)
        a1 = t - a3 * np.dot(a3, t)
        a1 /= np.linalg.norm(a1)
        b1, b3 = L.quat_to_exyz(L.exyz_to_quat(a1, a3))
        worst = max(worst, np.abs(b1 - a1).max(), np.abs(b3 - a3).max())
    assert worst < 1e-9


def test_dump_to_oxdna_traj_roundtrips_positions_and_orientation(tmp_path):
    # a 2-frame, 2-atom dump written in the column order build_input_file emits
    q1 = L.exyz_to_quat([1, 0, 0], [0, 0, 1])
    q2 = L.exyz_to_quat([0, 1, 0], [0, 0, 1])

    def frame(t):
        return (
            f"ITEM: TIMESTEP\n{t}\nITEM: NUMBER OF ATOMS\n2\n"
            "ITEM: BOX BOUNDS pp pp pp\n-10 10\n-10 10\n-10 10\n"
            "ITEM: ATOMS id mol type x y z c_quat[1] c_quat[2] c_quat[3] c_quat[4]\n"
            # deliberately out of id order → converter must sort by id
            f"2 1 4 3 4 5 {q2[0]} {q2[1]} {q2[2]} {q2[3]}\n"
            f"1 1 1 0 0 0 {q1[0]} {q1[1]} {q1[2]} {q1[3]}\n"
        )

    dump = frame(0) + frame(1000)
    out = tmp_path / "traj.dat"
    n = L.lammps_dump_to_oxdna_traj(dump, out)
    assert n == 2
    # 2 frames × 2 atoms → parse_configuration flattens all frames' nucleotide lines
    _box, entries = L.parse_configuration(out.read_text())
    assert len(entries) == 4
    # frame-0 atom id 1 comes first (converter sorts by id), at origin, a1≈(1,0,0) a3≈(0,0,1)
    assert list(entries[0].pos) == [0.0, 0.0, 0.0]
    assert np.allclose(entries[0].a1, [1, 0, 0], atol=1e-5)
    assert np.allclose(entries[0].a3, [0, 0, 1], atol=1e-5)
    assert list(entries[1].pos) == [3.0, 4.0, 5.0]  # atom id 2 second
    # the dumped box edge (hi-lo = 20) is preserved
    assert _box[0] == 20.0


# ── parsers ───────────────────────────────────────────────────────────────────


def test_parse_topology():
    n_strands, rows = L.parse_topology(_TOP)
    assert n_strands == 2
    assert len(rows) == 4
    assert (
        rows[0].strand == 1
        and rows[0].base == "A"
        and rows[0].n3 == 1
        and rows[0].n5 == -1
    )
    assert rows[3].n3 == -1 and rows[3].n5 == 2


def test_parse_configuration():
    box, entries = L.parse_configuration(_CONF)
    assert list(box) == [30.0, 30.0, 30.0]
    assert len(entries) == 4
    assert list(entries[1].pos) == [0.7, 0.0, 0.0]
    assert list(entries[1].a1) == [-1.0, 0.0, 0.0]
    assert list(entries[0].a3) == [0.0, 0.0, 1.0]


# ── data-file writer ──────────────────────────────────────────────────────────


def _data():
    return L.build_data_file(_TOP, _CONF)


def test_data_file_counts_and_types():
    data = _data()
    assert "4 atoms" in data
    assert "4 atom types" in data
    assert "4 ellipsoids" in data
    # 2 bonds: one per nucleotide that has a 3′ neighbour (nt0→nt1, nt2→nt3)
    assert "2 bonds" in data


def test_data_file_bonds_come_from_three_prime_neighbours():
    lines = _data().splitlines()
    bstart = lines.index("Bonds") + 2
    bonds = {tuple(int(x) for x in lines[bstart + i].split()[2:4]) for i in range(2)}
    assert bonds == {(1, 2), (3, 4)}


def test_data_file_atom_types_map_from_bases():
    lines = _data().splitlines()
    astart = lines.index("Atoms # hybrid") + 2
    types = [int(lines[astart + i].split()[1]) for i in range(4)]
    assert types == [1, 4, 1, 4]  # A,T,A,T → 1,4,1,4


def test_data_file_box_encloses_all_atoms_with_min_edge():
    lines = _data().splitlines()
    xlo, xhi = (
        float(v) for v in next(l for l in lines if l.endswith("xlo xhi")).split()[:2]
    )
    assert xhi - xlo >= 24.0  # min_box floor
    assert xlo <= 0.0 and xhi >= 0.7  # encloses the atom span


def test_data_file_ellipsoid_quaternions_are_unit_norm():
    lines = _data().splitlines()
    estart = lines.index("Ellipsoids") + 2
    for i in range(4):
        q = [float(v) for v in lines[estart + i].split()[4:8]]
        assert abs(np.linalg.norm(q) - 1.0) < 1e-9


def test_data_file_rejects_unsequenced_design():
    bad_top = _TOP.replace("1 A 1 -1", "1 N 1 -1")
    with pytest.raises(ValueError, match="not fully sequenced"):
        L.build_data_file(bad_top, _CONF)


def test_data_file_rejects_atom_count_mismatch():
    short_conf = "\n".join(_CONF.splitlines()[:5]) + "\n"  # drop 2 nucleotide lines
    with pytest.raises(ValueError, match="nucleotides"):
        L.build_data_file(_TOP, short_conf)


# ── input-script writer ───────────────────────────────────────────────────────


def test_input_file_has_all_six_oxdna2_pair_styles_and_fene():
    txt = L.build_input_file(L.LammpsInputParams())
    for style in (
        "oxdna2/excv",
        "oxdna2/stk",
        "oxdna2/hbond",
        "oxdna2/xstk",
        "oxdna2/coaxstk",
        "oxdna2/dh",
        "oxdna2/fene",
    ):
        assert style in txt
    assert "atom_style hybrid bond ellipsoid oxdna" in txt


def test_input_file_threads_run_parameters():
    p = L.LammpsInputParams(
        steps=1234,
        dump_every=7,
        traj_file="t.lammpstrj",
        data_file="d.data",
        temperature=0.09,
        salt_molar=0.3,
    )
    txt = L.build_input_file(p)
    assert "run 1234" in txt
    assert "read_data d.data" in txt
    assert "t.lammpstrj" in txt
    assert "0.09" in txt and "0.3" in txt


def test_input_file_has_soft_start_minimize_by_default():
    txt = L.build_input_file(L.LammpsInputParams(relax_iters=2000))
    assert "min_style fire" in txt
    assert "minimize 1e-4 1e-6 2000 20000" in txt
    assert "reset_timestep 0" in txt
    # the minimise must precede the production run + the dump (dumped traj = production)
    assert txt.index("minimize") < txt.index("dump traj")


def test_input_file_soft_start_can_be_disabled():
    txt = L.build_input_file(L.LammpsInputParams(relax_iters=0))
    assert "minimize" not in txt
    assert "reset_timestep" not in txt
    run_cmds = [ln for ln in txt.splitlines() if ln.startswith("run ")]
    assert len(run_cmds) == 1  # production run only, no warmup run


# ── external forces (oxDNA forces.txt → LAMMPS fixes) ─────────────────────────


def test_length_constant_matches_project_constants():
    from backend.core.constants import OXDNA_LENGTH_UNIT

    assert abs(L.OXDNA_LENGTH_UNIT - OXDNA_LENGTH_UNIT) < 1e-9
    assert abs(L.NM_TO_OXDNA - 1.0 / OXDNA_LENGTH_UNIT) < 1e-9


def test_compress_id_ranges_collapses_runs():
    assert L.compress_id_ranges([1, 2, 3, 7, 8, 10]) == "1:3 7:8 10"
    assert L.compress_id_ranges([5]) == "5"
    assert L.compress_id_ranges([]) == ""
    assert L.compress_id_ranges([3, 1, 2, 2]) == "1:3"  # sorted + deduped


def test_axis_wall_from_extent_places_wall_past_structure():
    pos = [[0, 0, 5.0], [0, 0, 9.0], [0, 0, 7.0]]
    # dir +z → allowed side above → 'zlo' wall at min z minus the offset
    assert L.axis_wall_from_extent(pos, [0, 0, 1], 0.0) == ("zlo", 5.0)
    assert L.axis_wall_from_extent(pos, [0, 0, 1], 1.5) == ("zlo", 3.5)
    # dir -z → allowed side below → 'zhi' wall at max z plus the offset
    assert L.axis_wall_from_extent(pos, [0, 0, -1], 1.0) == ("zhi", 10.0)


def test_axis_wall_rejects_non_axis_aligned_direction():
    with pytest.raises(ValueError, match="axis-aligned"):
        L.axis_wall_from_extent([[0, 0, 0]], [1, 1, 0], 0.0)


def test_build_force_fixes_emits_addforce_spring_and_wall():
    spec = L.LammpsForceSpec(
        force=(0.1, 0.0, 0.0),
        anchor_ids=[1, 2, 3, 7],
        anchor_stiff=1000.0,
        wall={"face": "zlo", "coord": 4.0, "epsilon": 50.0, "cutoff": 1.0},
    )
    txt = L.build_force_fixes(spec)
    assert "fix efield all addforce 0.1 0 0" in txt
    assert "group anchors id 1:3 7" in txt
    assert "fix anchors anchors spring/self 1000" in txt
    assert "fix surface all wall/harmonic zlo 4 50 1.0 1 units box" in txt


def test_build_force_fixes_empty_when_no_forces():
    assert L.build_force_fixes(None) == ""
    assert L.build_force_fixes(L.LammpsForceSpec()) == ""


def test_boundary_line_periodic_unless_walled():
    assert L.boundary_line(None) == "boundary p p p"
    assert L.boundary_line(L.LammpsForceSpec()) == "boundary p p p"
    lo = L.LammpsForceSpec(wall={"face": "zlo", "coord": 0.0})
    assert L.boundary_line(lo) == "boundary p p fm"  # wall face fixed, opposite shrink
    hi = L.LammpsForceSpec(wall={"face": "xhi", "coord": 0.0})
    assert L.boundary_line(hi) == "boundary mf p p"


def test_input_file_injects_forces_into_production_block_after_minimise():
    spec = L.LammpsForceSpec(force=(0.5, 0, 0), anchor_ids=[1, 2], anchor_stiff=1000.0)
    txt = L.build_input_file(L.LammpsInputParams(relax_iters=100), spec)
    assert "fix efield all addforce" in txt
    assert "fix anchors anchors spring/self 1000" in txt
    # spring/self must be created AFTER the minimise (tethers to production-start pos)
    assert txt.index("minimize") < txt.index("spring/self")
    # and before the production run
    assert txt.index("spring/self") < txt.index("run 100")


def test_input_file_without_force_spec_is_unchanged():
    assert "addforce" not in L.build_input_file(L.LammpsInputParams())
    assert L.build_input_file(L.LammpsInputParams()).count("boundary p p p") == 1
