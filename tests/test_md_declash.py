"""Unit tests for the declash MD protocol (single-stranded inserted-base designs).

The declash route minimises clashed single-stranded bases out of steric overlap,
re-anchors references to the declashed coordinates, and runs the ladder with the
soft integrator.  These tests cover the pure config/IO pieces; the MDAnalysis
pair-detection and full NAMD round-trip are validated manually against a real
package.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from types import SimpleNamespace as NS

from backend.core import md_protocols as M


# ── Auto-detection of extra-base designs ──────────────────────────────────────


def test_design_has_extra_bases_detects_crossover_insertions():
    plain = NS(
        crossovers=[NS(extra_bases=None), NS(extra_bases="")], forced_ligations=[]
    )
    twoxt = NS(
        crossovers=[NS(extra_bases=None), NS(extra_bases="TT")], forced_ligations=[]
    )
    assert not M.design_has_extra_bases(plain)
    assert M.design_has_extra_bases(twoxt)


def test_design_has_extra_bases_detects_forced_ligations():
    d = NS(crossovers=[], forced_ligations=[NS(extra_bases="T")])
    assert M.design_has_extra_bases(d)


# ── Soft integrator ───────────────────────────────────────────────────────────


def _spec(soft: bool) -> M.SegmentSpec:
    return M.SegmentSpec(
        name="t_01_300K_NPT_ENM_k0p5_p10",
        stage="300K NPT ENM k=0.5",
        percent=10.0,
        steps=2400,
        temp=300.0,
        damping=5.0,
        scale=0.5,
        npt=True,
        previous="t_00_min",
        extra_bonds_file="t_k0.5.enm.extra",
        soft=soft,
    )


def test_soft_segment_uses_flexible_bonds_and_1fs():
    conf = M._segment_conf(_spec(soft=True), "t", (80.0, 80.0, 200.0), True)
    assert "rigidBonds         none" in conf
    assert "timestep           1" in conf


def test_standard_segment_uses_rigid_bonds_and_2fs():
    conf = M._segment_conf(_spec(soft=False), "t", (80.0, 80.0, 200.0), True)
    assert "rigidBonds         all" in conf
    assert "timestep           2" in conf


def test_segments_soft_flag_propagates():
    _, soft_segs = M.mgh_slow_release_segments("t", soft=True)
    _, hard_segs = M.mgh_slow_release_segments("t", soft=False)
    assert soft_segs and all(s.soft for s in soft_segs)
    # Soft start: the first segment whose solute atoms MOVE is always soft (it relaxes
    # the strained start past the RATTLE failure); every later segment reverts to rigid
    # 2 fs.  The Note-4 settle stage runs earlier with all DNA fixed, so it is excluded —
    # nothing can strain there.
    free = [s for s in hard_segs if s.fixed_atoms_file is None]
    assert free and free[0].gentle
    assert not any(s.gentle for s in free[1:])


def test_declash_gets_the_gentle_tier_not_the_flexible_one():
    """exp49: an ideal build with 60 inserted crossover bases survived 25 ps at 2 fs with
    rigid bonds.  The 1 fs flexible-bond ladder was costing 2x across all 19.2 ns for
    protection it did not need.  force_soft remains the explicit escape hatch."""
    _, declash = M.mgh_slow_release_segments("t", gentle=True)
    _, forced = M.mgh_slow_release_segments("t", soft=True)
    assert all(s.gentle and not s.soft for s in declash)
    assert all(s.soft for s in forced)
    assert M.effective_timestep_fs(declash[0], fast=True) == 2.0
    assert M.effective_timestep_fs(forced[0], fast=True) == 1.0


def test_min_conf_enm_override():
    box = (80.0, 80.0, 200.0)
    default = M._min_conf("t_00_min", "t", box, True, 4800, 0.5)
    declash = M._min_conf(
        "t_00_min", "t", box, True, 4800, 0.5, enm_file="t_declash_k0.5.enm.extra"
    )
    assert "t_k0.5.enm.extra" in default
    assert "t_declash_k0.5.enm.extra" in declash
    assert "t_k0.5.enm.extra" not in declash.replace("t_declash_k0.5.enm.extra", "")


# ── Manifest round-trip preserves soft ────────────────────────────────────────


def test_manifest_roundtrip_preserves_soft(tmp_path: Path):
    _, segs = M.mgh_slow_release_segments("t", soft=True)
    manifest = {
        "minimization": {"name": "t_00_min"},
        "segments": [
            {
                "name": s.name,
                "stage": s.stage,
                "percent": s.percent,
                "steps": s.steps,
                "temp": s.temp,
                "damping": s.damping,
                "scale": s.scale,
                "npt": s.npt,
                "previous": s.previous,
                "reinit": s.reinit,
                "dcd_freq": s.dcd_freq,
                "min_c1_paired": s.min_c1_paired,
                "min_wc_ref_relative": s.min_wc_ref_relative,
                "extra_bonds_file": s.extra_bonds_file,
                "soft": s.soft,
            }
            for s in segs
        ],
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest))
    _, restored = M.segments_from_manifest(p)
    assert all(s.soft for s in restored)


# ── write_declashed_pdb: coordinate overwrite is byte-faithful ────────────────


def test_write_declashed_pdb_overwrites_only_coords(tmp_path: Path):
    # Two atoms: one ATOM (DNA), one HETATM (water) — preserve record/chain/resid.
    src = (
        "ATOM      1  C1' DT  A   1      11.111  22.222  33.333  1.00  0.00      DNAA\n"
        "HETATM    2  OH2 TIP3W   1      44.444  55.555  66.666  1.00  0.00      W000\n"
    )
    src_pdb = tmp_path / "src.pdb"
    src_pdb.write_text(src)

    # NAMD .coor: int32 count + N*3 float64, declashed coordinates.
    new = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    blob = struct.pack("<i", 2) + b"".join(struct.pack("<3d", *xyz) for xyz in new)
    coor = tmp_path / "min.coor"
    coor.write_bytes(blob)

    dst = tmp_path / "dst.pdb"
    n = M.write_declashed_pdb(coor, src_pdb, dst)
    assert n == 2

    lines = dst.read_text().splitlines()
    assert lines[0].startswith("ATOM") and lines[1].startswith("HETATM")
    # coords replaced
    assert lines[0][30:54] == f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}"
    assert lines[1][30:54] == f"{4.0:8.3f}{5.0:8.3f}{6.0:8.3f}"
    # everything else preserved (atom name, residue, chain, segid tail)
    assert "C1'" in lines[0] and "DNAA" in lines[0]
    assert "TIP3W" in lines[1] and "W000" in lines[1]


def test_write_declashed_pdb_atom_count_mismatch_raises(tmp_path: Path):
    src_pdb = tmp_path / "src.pdb"
    src_pdb.write_text("ATOM      1  C1' DT  A   1      11.1  22.2  33.3  1.00  0.00\n")
    coor = tmp_path / "min.coor"
    coor.write_bytes(
        struct.pack("<i", 2) + b"".join(struct.pack("<3d", 0, 0, 0) for _ in range(2))
    )
    dst = tmp_path / "dst.pdb"
    try:
        M.write_declashed_pdb(coor, src_pdb, dst)
        assert False, "expected RuntimeError on atom-count mismatch"
    except RuntimeError:
        pass


# ── ENM exclusion drops the right springs ─────────────────────────────────────


def test_enm_exclude_residues_reduces_springs(tmp_path: Path):
    # Minimal PDB: a few DNA base-ring atoms across two chains close enough to
    # bond.  Excluding one residue must drop its springs.
    def atom(serial, name, resn, chain, resid, x, y, z):
        return (
            f"ATOM  {serial:5d}  {name:<3s} {resn:<3s} {chain}{resid:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00\n"
        )

    # Two residues (A:1, B:1) with overlapping base-ring atoms within 8 A.
    lines = []
    s = 1
    for chain, base_x in (("A", 0.0), ("B", 3.0)):
        for nm, dx in (("N1", 0.0), ("C2", 1.0), ("N3", 2.0)):
            lines.append(atom(s, nm, "DT", chain, 1, base_x + dx, 0.0, 0.0))
            s += 1
    pdb = tmp_path / "t.pdb"
    pdb.write_text("".join(lines))

    full = M.write_aksimentiev_enm_files(pdb, tmp_path, "t", scales=(0.5,))
    excl = M.write_aksimentiev_enm_files(
        pdb,
        tmp_path,
        "t_x",
        scales=(0.5,),
        exclude_residues={("B", "1")},
    )
    assert excl["n_restraints_per_file"] < full["n_restraints_per_file"]


# ── ENM grouping survives chain-id aliasing at large strand counts ────────────


def test_enm_grouping_does_not_merge_distant_cycled_chain_collisions(tmp_path: Path):
    """Distant residues that alias on (chain, resid, resname) stay separate nodes.

    Past 62 strands ``_chain_char`` cycles and resids repeat across strands, so two
    physically distant residues collide on (chain, resid).  The old global-dict
    keying merged every such collision into one ENM node — averaging a nonsense
    centre-of-mass across the two locations — for ~half the residues of the
    224-strand 18hb.  Contiguity grouping keeps each physical base its own node.
    """

    def atom(serial, name, resn, chain, resid, x, y, z):
        return (
            f"ATOM  {serial:5d}  {name:<3s} {resn:<3s} {chain}{resid:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00\n"
        )

    # res1 (A:1) at origin, res2 (B:2) elsewhere, res3 (A:1 — SAME key as res1)
    # 1000 Å away.  No TER between them: only contiguity can keep res1/res3 apart.
    blocks = [("A", 1, 0.0), ("B", 2, 100.0), ("A", 1, 1000.0)]
    lines, s = [], 1
    for chain, resid, base in blocks:
        for nm, dx in (("N1", 0.0), ("C2", 1.0), ("N3", 2.0)):
            lines.append(atom(s, nm, "DT", chain, resid, base + dx, 0.0, 0.0))
            s += 1
    pdb = tmp_path / "cyc.pdb"
    pdb.write_text("".join(lines))

    residues = M._parse_base_ring_residues(pdb)
    assert len(residues) == 3, "distant same-key residues must not merge into one node"
    xs = sorted(r.com[0] for r in residues)
    assert xs[0] < 10 and 90 < xs[1] < 110 and xs[2] > 990


def test_fast_prepare_does_not_reference_a_removed_variable():
    """Regression: `fast = fast and not soft_ladder` outlived the variable it read.

    Python short-circuits `False and ...`, so this NameError was invisible to every test
    that prepared with the default fast=False — and would have crashed EVERY fast prepare
    at runtime.  Compile-check the module and assert the surviving expression is the
    intended one.
    """
    import io
    import inspect
    import tokenize

    src = inspect.getsource(M.prepare_mgh_slow_release)
    assert "fast = fast and not force_soft" in src
    # Token-level, so a mention in a COMMENT does not count — only real identifiers.
    names = {tok.string for tok in tokenize.generate_tokens(io.StringIO(src).readline)
             if tok.type == tokenize.NAME}
    assert "soft_ladder" not in names
