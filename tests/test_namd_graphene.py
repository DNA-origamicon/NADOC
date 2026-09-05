"""Wall force-field regressions: no real MD, geometry generation, or GPU required."""

import asyncio
import json
import math
import shutil

import pytest

from backend.core import namd_graphene as wall


def test_wall_npt_piston_is_gentle_across_segments():
    conf = (
        "timestep 4\nconstraints on\nconsref wall.pdb\n"
        "langevinPiston on\nlangevinPistonPeriod 1000\n"
        "langevinPistonDecay 500\nrun 120000\n"
    )
    fixed = wall.graphene_pressure_conf(conf, enabled=True)
    assert "langevinPistonPeriod 10000.0" in fixed
    assert "langevinPistonDecay 5000.0" in fixed
    assert "timestep 4\nconstraints on\nconsref wall.pdb" in fixed
    assert "run 120000" in fixed
    assert wall.graphene_pressure_conf(fixed, enabled=True) == fixed
    assert wall.graphene_pressure_conf(conf, enabled=False) == conf
    nvt = conf.replace("langevinPiston on", "langevinPiston off")
    assert wall.graphene_pressure_conf(nvt, enabled=True) == nvt
    slower = fixed.replace("10000.0", "20000.0").replace("5000.0", "10000.0")
    assert wall.graphene_pressure_conf(slower, enabled=True) == slower
from backend.core.namd_solvate import _extend_psf, _FF_DIR, _FF_FILES


BASE_PSF = """PSF EXT

         1 !NATOM
         1 DNA      1        PHE      CA       CA           0.000000     12.011000        0

         0 !NBOND: bonds

         0 !NTHETA: angles

         0 !NPHI: dihedrals

         0 !NIMPHI: impropers

         0 !NNB

"""


def parameters(path):
    nonbonded, pairs = {}, {}
    section = None
    for line in path.read_text().splitlines():
        words = line.split("!", 1)[0].split()
        if not words or words[0].startswith("*"):
            continue
        if words[0].upper() in ("NONBONDED", "NBFIX", "END", "HBOND"):
            section = words[0].upper()
            continue
        if section == "NONBONDED" and len(words) >= 4:
            try:
                nonbonded[words[0]] = (abs(float(words[2])), float(words[3]))
            except ValueError:
                pass
        if section == "NBFIX" and len(words) >= 4:
            pairs[tuple(sorted(words[:2]))] = (abs(float(words[2])), float(words[3]))
    return nonbonded, pairs


def lj_pair(a, b, distance, nonbonded, pairs):
    epsilon, rmin = pairs.get(
        tuple(sorted((a, b))),
        (
            math.sqrt(nonbonded[a][0] * nonbonded[b][0]),
            nonbonded[a][1] + nonbonded[b][1],
        ),
    )
    ratio6 = (rmin / distance) ** 6
    return (
        epsilon * (ratio6**2 - 2 * ratio6),
        12 * epsilon / distance * (ratio6**2 - ratio6),
    )


def test_wall_self_force_removed_without_changing_solvent_or_protein_interactions():
    nb, pairs = parameters(_FF_DIR / "par_all36m_prot.prm")
    wall_nb, wall_pairs = parameters(_FF_DIR / "par_np_thiol.prm")
    nb.update(wall_nb)
    pairs.update(wall_pairs)
    # Representative non-wall site. NGRC has CA's mixing parameters, not zero epsilon.
    nb["water"] = (0.1521, 1.7682)
    energy, force = lj_pair("CA", "CA", 1.42, nb, pairs)
    assert energy == pytest.approx(16623.93719433381)
    assert force > 140000
    for distance in (1.42, 2.44, 3.35):
        assert lj_pair(
            wall.GRAPHENE_ATOM_TYPE, wall.GRAPHENE_ATOM_TYPE, distance, nb, pairs
        ) == (0, 0)
        assert lj_pair(
            wall.GRAPHENE_ATOM_TYPE, "water", distance, nb, pairs
        ) == lj_pair("CA", "water", distance, nb, pairs)
        assert lj_pair(wall.GRAPHENE_ATOM_TYPE, "CA", distance, nb, pairs) == lj_pair(
            "CA", "CA", distance, nb, pairs
        )
    assert "par_np_thiol.prm" in _FF_FILES


def test_psf_uses_wall_type_across_segment_boundaries_without_changing_protein_ca():
    psf = _extend_psf(BASE_PSF, [], [], [], graphene_atoms=10001)
    rows = [line.split() for line in psf.splitlines() if " GRP " in line]
    assert len(rows) == 10001
    assert {row[5] for row in rows} == {wall.GRAPHENE_ATOM_TYPE}
    assert rows[9999][1] == "GR01"
    assert all(float(row[6]) == 0 and float(row[7]) == 12.011 for row in rows)
    assert "PHE      CA       CA" in psf


@pytest.fixture
def package(tmp_path):
    spec = {"material": "graphene"}
    wall.describe_graphene_wall(spec)
    (tmp_path / "manifest.json").write_text(json.dumps({"graphene_nanopore": spec}))
    (tmp_path / "system.psf").write_text(
        _extend_psf(BASE_PSF, [], [], [], graphene_atoms=2)
    )
    (tmp_path / "forcefield").mkdir()
    shutil.copy2(_FF_DIR / "par_np_thiol.prm", tmp_path / "forcefield/par_np_thiol.prm")
    return tmp_path


def test_corrected_package_validates(package):
    wall.validate_graphene_wall_package(package)


def test_legacy_package_requires_rebuild(package):
    (package / "manifest.json").write_text(
        '{"graphene_nanopore":{"material":"graphene"}}'
    )
    with pytest.raises(ValueError, match="Copy this job and press Run"):
        wall.validate_graphene_wall_package(package)


@pytest.mark.parametrize("broken", ["hmr_type", "self_pair", "site_epsilon"])
def test_metadata_alone_does_not_approve_unsafe_inputs(package, broken):
    if broken == "hmr_type":
        (package / "system_hmr.psf").write_text(
            (package / "system.psf").read_text().replace("NGRC", "CA  ")
        )
    else:
        path = package / "forcefield/par_np_thiol.prm"
        text = path.read_text()
        text = (
            text.replace("NGRC NGRC", "CA CA")
            if broken == "self_pair"
            else text.replace("-0.070000", "0.000000")
        )
        path.write_text(text)
    with pytest.raises(ValueError):
        wall.validate_graphene_wall_package(package)


@pytest.mark.parametrize("resume", [False, True])
def test_alpine_refuses_legacy_wall_before_remote_operations(tmp_path, resume):
    from tests.test_md_executor import _make_prepared_job, FakeConn
    from backend.core import md_executor, cluster_config, cluster_resources

    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    manifest = json.loads((pkg / "manifest.json").read_text())
    manifest["graphene_nanopore"] = {"material": "graphene"}
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    profile = cluster_config.alpine_profile()
    conn = FakeConn()
    job.remote_scratch_dir = "/scratch/old-wall"
    if resume:
        call = md_executor.resume_job(job, tmp_path, profile=profile, conn=conn)
    else:
        resources = cluster_resources.recommend(profile, n_atoms=100000, total_ns=1)
        call = md_executor.submit_job(
            job, tmp_path, profile=profile, resources=resources, conn=conn
        )
    with pytest.raises(ValueError, match="Legacy graphene wall"):
        asyncio.run(call)
    assert conn.puts == []
    assert conn.runs == []
