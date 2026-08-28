from pathlib import Path
import asyncio
from types import SimpleNamespace

from backend.core import cluster_oxdna_build as build
from backend.core.cluster_config import alpine_profile


def test_build_script_compiles_adaptive_cuda_for_a100_and_h200():
    script = build.build_sbatch(
        build_dir="/projects/u/nadoc_jobs/nadoc_builds/oxdna-adaptive",
        source_name="source", tar_name="oxdna-adaptive.tar.gz",
    )
    assert "#SBATCH --partition=acpu" in script
    assert "-DCUDA=ON" in script
    assert "-DCMAKE_CUDA_ARCHITECTURES='80;90'" in script
    assert "--target oxDNA DNAnalysis" in script
    assert "adaptive-memory" in script
    assert "g++ -print-file-name=libstdc++.so.6" in script
    assert "gcc -print-file-name=libgcc_s.so.1" in script
    assert "oxDNA' 2>&1 | head -20 || true" not in script
    assert "existing adaptive-memory oxDNA install verified" in script
    assert "oxDNA' --help 2>&1 || true) | grep" in script
    assert "DNAnalysis' --help 2>&1 || true) | grep" in script


def test_build_dir_is_confined_to_project_builds():
    path = build.build_dir_for(alpine_profile(), "jojo", "oxdna-adaptive")
    assert path == "/projects/jojo/nadoc_jobs/nadoc_builds/oxdna-adaptive"


def test_tarball_excludes_git_and_old_builds(tmp_path):
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "build-old").mkdir()
    (source / "src").mkdir()
    (source / ".git" / "x").write_text("x")
    (source / "build-old" / "x").write_text("x")
    (source / "src" / "x.cpp").write_text("x")
    target = tmp_path / "source.tar.gz"
    build.make_source_tarball(source, target)
    import tarfile
    with tarfile.open(target) as archive:
        names = archive.getnames()
    assert "source/src/x.cpp" in names
    assert not any(".git" in name or "build-old" in name for name in names)


def test_run_build_uses_base_cluster_upload_interface(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "CMakeLists.txt").write_text("project(test)")

    class Connection:
        user = "jojo"

        def __init__(self):
            self.uploads = []

        async def mkdir_p(self, _remote):
            pass

        async def sftp_put(self, local, remote):
            self.uploads.append((Path(local).read_bytes(), remote))

        async def run(self, _command):
            return SimpleNamespace(stdout="Submitted batch job 12345", stderr="")

    conn = Connection()
    state = asyncio.run(build.run_build(
        conn, alpine_profile(), source_dir=source, name="test-build",
    ))
    assert state["slurm_job_id"] == "12345"
    assert any(remote.endswith("/build.sbatch") for _, remote in conn.uploads)
