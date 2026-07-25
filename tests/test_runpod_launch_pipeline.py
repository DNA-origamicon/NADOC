"""Spec-driven RunPod NAMD launcher: the ASSESS input (atom count read from the package PSF)
and the build/arch spec layer. The rent/run/reroll loop itself needs a live pod, so it is not
unit-tested here — these cover the pure, money-free pieces the launcher depends on."""
import tarfile

from experiments.exp43_runpod_bench.launch_voltron_compact import (
    BUILD_CC, SPECS, natom_from_package, voltron_compact_spec,
)


def _psf_text(natom: int, ntitle: int) -> str:
    # A real psfgen PSF puts !NATOM AFTER a !NTITLE block that can be thousands of REMARKS lines
    # (one per patch) — the reason a naive small read-cap missed it.
    lines = ["PSF", "", f"   {ntitle} !NTITLE"]
    lines += [f" REMARKS patch {i}" for i in range(ntitle)]
    lines += ["", f" {natom} !NATOM", "       1 D000 1 ADE ..."]
    return "\n".join(lines) + "\n"


def _tar_with(tmp_path, members: dict[str, str]):
    tar = tmp_path / "pkg.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        for name, text in members.items():
            p = tmp_path / name.replace("/", "_")
            p.write_text(text)
            t.add(p, arcname=name)
    return tar


def test_natom_read_past_big_ntitle_block(tmp_path):
    tar = _tar_with(tmp_path, {"pkg/sys.psf": _psf_text(1_310_154, ntitle=15_392)})
    assert natom_from_package(tar) == 1_310_154


def test_natom_ignores_hmr_sibling(tmp_path):
    # The HMR PSF has the same atoms but we want the base PSF as the canonical source.
    tar = _tar_with(tmp_path, {
        "pkg/sys.psf": _psf_text(1_310_154, ntitle=10),
        "pkg/sys_hmr.psf": _psf_text(9_999_999, ntitle=10),
    })
    assert natom_from_package(tar) == 1_310_154


def test_natom_missing_psf_returns_none(tmp_path):
    tar = _tar_with(tmp_path, {"pkg/readme.txt": "no psf here"})
    assert natom_from_package(tar) is None


def test_natom_bad_tar_returns_none(tmp_path):
    bad = tmp_path / "nope.tar.gz"
    bad.write_text("not a tar")
    assert natom_from_package(bad) is None


def test_build_cc_git_has_no_sm120():
    assert "12.0" not in BUILD_CC["git"], "git build cannot run the 5090 (sm_120)"
    assert "8.9" in BUILD_CC["git"]           # 4090
    assert "12.0" in BUILD_CC["release"]      # the multi-arch 3.0.2 tar does


def test_specs_registry_and_voltron_default():
    assert "voltron_compact" in SPECS
    s = voltron_compact_spec()
    assert s.build == "git" and s.name == "voltron_compact"
    assert s.timestep_fs == 4.0 and s.alt_timestep_fs == 2.0
    assert s.pod_prefix == "nadoc-bench"      # so pod_watchdog guards it
