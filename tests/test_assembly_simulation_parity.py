"""Representative assembly seam for every non-atomistic prepared-job backend.

The engine APIs deliberately remain Design-based.  Assembly mode materializes its
complete world-space topology into that shared Design slot, then all existing job
lifecycle code is reused.  BigO-poly is the acceptance fixture because it is the
representative one-instance assembly used for part/assembly parity.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state, state as design_state
from backend.api.main import app
from backend.core.cando_job import CandoJob
from backend.core.mrdna_job import MrdnaJob
from backend.core.lammps_job import LammpsJob, LammpsStatus
from backend.core.md_job import MdJob, MdStatus, new_job as new_md_job
from backend.core.oxdna_job import OxdnaJob
from backend.core.snupi_job import SnupiJob


ROOT = Path(__file__).parents[1]
BIG_O_POLY = ROOT / "workspace" / "BigO-poly.nass"


@pytest.fixture
def assembly_sim_client(tmp_path, monkeypatch):
    if not BIG_O_POLY.exists():
        pytest.skip("optional workspace/BigO-poly.nass parity fixture is unavailable")

    from backend.api import assembly as routes_assembly
    from backend.api import (
        routes_cando, routes_lammps, routes_md, routes_mrdna, routes_oxdna,
        routes_snupi,
    )

    for module in (
        routes_assembly, routes_cando, routes_lammps, routes_md, routes_mrdna,
        routes_oxdna, routes_snupi,
    ):
        monkeypatch.setattr(module, "_WORKSPACE_DIR", tmp_path)

    # Exercise the real LAMMPS input preparation but stop at the launch seam; a
    # prepared queued job is the lifecycle equivalent of autostart=False on the
    # other engines and keeps this fast test from running molecular dynamics.
    def queue_lammps(job, workspace):
        job.status = LammpsStatus.queued
        job.save(workspace)

    monkeypatch.setattr(routes_lammps.lammps_runner, "start_job", queue_lammps)

    # NAMD creation normally starts the 60-120 s solvation/preparation coroutine.
    # Pin the route-to-shared-design seam here and persist its frozen topology, while
    # real NAMD execution remains in the guarded slow/manual validation group.
    def queue_namd(body, *, design, seeded, name, size_factor, **_kwargs):
        assert not seeded
        assert len(design.helices) == 56 and len(design.strands) == 177
        job = new_md_job(
            design_name=name, protocol=body.protocol, name_stem="", package_subdir="",
            threads=body.threads, devices=body.devices,
            design_source_path=body.design_source_path,
        )
        job.status = MdStatus.queued
        job.prep_params = body.model_dump()
        job.save(tmp_path)
        job.job_dir(tmp_path).mkdir(parents=True, exist_ok=True)
        (job.job_dir(tmp_path) / "design.json").write_text(design.to_json())
        return job

    monkeypatch.setattr(routes_md, "_spawn_prep_job", queue_namd)

    doc = "__test_assembly_sim_parity__"
    headers = {"X-NADOC-Doc": doc}
    client = TestClient(app)
    loaded = client.post(
        "/api/assembly/load", json={"path": str(BIG_O_POLY)}, headers=headers
    )
    assert loaded.status_code == 200, loaded.text
    materialized = client.post(
        "/api/assembly/flatten/load-as-design", headers=headers
    )
    assert materialized.status_code == 200, materialized.text
    payload = materialized.json()
    assert len(payload["design"]["helices"]) == 56
    assert len(payload["design"]["strands"]) == 177

    yield client, headers, tmp_path

    design_state.drop_doc(doc)
    assembly_state.drop_doc(doc)


def test_bigo_poly_prepares_shared_engine_jobs_and_unified_lifecycle(
    assembly_sim_client,
):
    client, headers, workspace = assembly_sim_client
    source = "BigO-poly.nass"
    requests = {
        "oxdna": (
            "/api/oxdna/jobs",
            {
                "backend": "CUDA", "mc_steps": 100, "md_relax_steps": 100,
                "equil_steps": 100, "autostart": False,
                "design_source_path": source,
            },
        ),
        "cando": (
            "/api/cando/jobs",
            {
                "nonlinear": False, "with_rmsf": False,
                "with_thermal_fluctuations": False, "autostart": False,
                "design_source_path": source,
            },
        ),
        "snupi": (
            "/api/snupi/jobs",
            {
                "nonlinear": False, "with_rmsf": False, "material": "snupi",
                "autostart": False, "design_source_path": source,
            },
        ),
        "mrdna": (
            "/api/mrdna/jobs",
            {
                "coarse_steps": 1_000, "fine_steps": 0, "output_period": 100,
                "autostart": False, "design_source_path": source,
            },
        ),
        "lammps": (
            "/api/lammps/jobs",
            {
                "steps": 1_000, "dump_every": 100, "ranks": 1,
                "design_source_path": source,
            },
        ),
        "namd": (
            "/api/md/jobs",
            {"autostart": False, "design_source_path": source},
        ),
    }

    created = {}
    for engine, (path, body) in requests.items():
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200, f"{engine}: {response.text}"
        job = response.json()
        assert job["status"] == "queued"
        if engine == "lammps":
            assert job["n_atoms"] == 14_112
        elif engine != "namd":
            assert job["n_nucleotides"] == 14_112
        assert job["design_source_path"] == source
        created[engine] = job["job_id"]

    # Every backend persisted the SAME namespaced flattened topology, rather than
    # preparing just the source part or an empty assembly shell.
    models = {
        "oxdna": OxdnaJob, "cando": CandoJob,
        "snupi": SnupiJob, "mrdna": MrdnaJob, "namd": MdJob,
    }
    for engine, model in models.items():
        job = model.load(created[engine], workspace)
        snapshot = job.job_dir(workspace) / "design.json"
        assert snapshot.exists(), f"{engine} did not persist its simulation topology"
        text = snapshot.read_text()
        assert "inst-7a49906c-dda1-4256-83ee-cf1510467a32::" in text

    lammps = LammpsJob.load(created["lammps"], workspace)
    assert (lammps.job_dir(workspace) / "data.oxdna").exists()
    assert (lammps.job_dir(workspace) / "in.lammps").exists()

    # The shared Jobs card must discover, scope, normalize, and expose progress/status
    # for each assembly run exactly as it does for a part run.
    response = client.get(
        "/api/simulate/jobs",
        params={"design_source_path": source, "show_all": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    nodes = {node["engine"]: node for node in response.json() if node["job_id"] in created.values()}
    assert set(nodes) == set(created)
    for engine, node in nodes.items():
        assert node["status"] == "queued", engine
        assert node["design_source_path"] == source

    # Engine progress endpoints back the shared master bar after row selection.
    for engine in ("cando", "snupi", "mrdna"):
        progress = client.get(
            f"/api/{engine}/jobs/{created[engine]}/progress", headers=headers
        )
        assert progress.status_code == 200, progress.text
        assert 0.0 <= progress.json()["overall"] <= 1.0

    # oxDNA carries staged progress in the normalized node itself; a prepared job
    # starts with all stages pending and an honest zero fraction.
    ox = nodes["oxdna"]
    assert ox["stages"] and all(stage["status"] == "pending" for stage in ox["stages"])
    assert ox.get("progress_fraction", 0.0) == 0.0
