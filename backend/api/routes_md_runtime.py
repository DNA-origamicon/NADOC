"""Read-only comparison of the same planned work on local, Alpine and Runpod."""

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from backend.api.routes_runpod import JobPreviewRequest
from backend.core.namd_planning import phase_work, stage_resident
from backend.core.namd_runtime import completion_quote, local_compute
from backend.core.disk_guard import namd_run_output_bytes

router = APIRouter()
_stock_cache = {}


class RuntimePreviewRequest(JobPreviewRequest):
    threads: int = Field(16, ge=1)
    devices: str = "0"
    partition: str = "ah200"
    gres_type: str | None = None


async def resolve_size(body, *, estimator=None):
    """A continuation uses its prepared parent, never the current open design."""
    if body.parent_job_id:
        from backend.api.routes_md import _load_job, _workspace
        from backend.core.cluster_resources import n_atoms_from_manifest

        job = _load_job(body.parent_job_id)
        try:
            manifest = json.loads(
                (job.package_dir(_workspace()) / "manifest.json").read_text()
            )
            atoms = n_atoms_from_manifest(manifest)
            box = [float(v) / 10 for v in manifest["box_ang"]]
            if atoms <= 0:
                raise ValueError("No atom count")
            return atoms, box, "prepared parent"
        except (OSError, KeyError, ValueError) as exc:
            raise HTTPException(
                400,
                "Prepared parent size is unavailable; cannot quote a different design.",
            ) from exc
    box = (
        list(body.box_size_nm)
        if body.box_size_nm and all(v and v > 0 for v in body.box_size_nm)
        else None
    )
    if body.n_atoms:
        return body.n_atoms, box, "provided"
    from backend.api import state
    from backend.core.md_vram import estimate_profile_from_design

    try:
        design = state.get_or_404().without_reference_geometry()
    except HTTPException:
        return None, box, "unknown"
    profile = await run_in_threadpool(
        estimator or estimate_profile_from_design,
        design,
        **({"padding_nm": body.padding_nm} if body.padding_nm else {}),
        box_mode=body.box_mode,
        box_size_nm=body.box_size_nm,
        nacl_mM=0 if body.salt_mode == "screening" else body.ion_conc_mM,
        mgcl2_mM=12.5 if body.salt_mode == "screening" else body.mg_conc_mM,
    )
    if not profile:
        return None, box, "unknown"
    return (
        profile.get("atom_upper_bound")
        or profile["dna_atoms"] + 3 * profile["full_water"] + profile["ion_atoms"],
        profile.get("resource_box_nm") or profile.get("box_nm"),
        "estimated",
    )


def work_for(body, n_atoms):
    from backend.core.md_integrator import resident_decision
    from backend.core.md_protocols import _RESIDENT_MIN_ATOMS

    resident = resident_decision(
        n_atoms=n_atoms,
        force_resident={"on": True, "off": False}.get(body.gpu_resident_mode),
        min_atoms=_RESIDENT_MIN_ATOMS,
    ).on
    work = phase_work(
        body.stages,
        relax_ns=body.relax_ns,
        production_ns=body.production_ns,
        relax_timestep_fs=body.relax_timestep_fs,
        production_timestep_fs=body.production_timestep_fs,
        resident=resident,
    )
    return [dict(s, gpu_resident=stage_resident(s, resident)) for s in work], resident


def attach_runpod_quotes(rows, body, n_atoms, box_nm, volume):
    from backend.core import runpod_s3

    work, _ = work_for(body, n_atoms)
    output = namd_run_output_bytes(
        [(s.get("steps", 0), s.get("dcd_freq", 0)) for s in work], n_atoms
    )
    # Mirrors executor's pre-rental staging branch. Validation still gates launch.
    s3 = bool(runpod_s3.resolve_credentials() and (volume or {}).get("data_center_id"))
    for row in rows:
        row["completion"] = completion_quote(
            row.get("compute"),
            target="runpod",
            n_atoms=n_atoms,
            stages=work,
            prepared=body.prepared or bool(body.parent_job_id),
            package_bytes=body.package_bytes,
            output_bytes=output,
            upload_mbps=body.upload_mbps,
            download_mbps=body.download_mbps,
            transfer_mode="s3" if s3 else "ssh",
            hourly_rate=row["usd_per_hour"],
            volume_size_gb=(volume or {}).get("size_gb"),
        )


async def live_stock():
    from backend.api import routes_runpod as rp

    if not rp._SESSION.is_connected() or not rp._SESSION.api_key:
        return None
    # Do not publish credentials, or keep prices across account/session changes.
    key = id(rp._SESSION.require())
    if (
        _stock_cache.get("session") == key
        and time.monotonic() - _stock_cache.get("at", 0) < 60
    ):
        return _stock_cache.get("stock")
    try:
        stock = await asyncio.wait_for(
            rp.runpod_preflight.fetch_gpu_stock(rp._SESSION.api_key), timeout=10
        )
        _stock_cache.update(session=key, at=time.monotonic(), stock=stock)
        return stock
    except (Exception, asyncio.TimeoutError):
        return None


@router.post("/md/runtime-preview")
async def runtime_preview(body: RuntimePreviewRequest):
    from backend.api import routes_cluster, routes_runpod
    from backend.core import cluster_config, cluster_resources, runpod_select

    n_atoms, box, source = await resolve_size(body)
    if not n_atoms:
        return dict(
            sized=False,
            reason="Load a design or choose a prepared parent to estimate duration.",
        )
    work, resident = work_for(body, n_atoms)
    if not work:
        return dict(
            sized=False, reason="Choose the simulation stages and duration first."
        )
    # Current local hardware match is mandatory; CPU-only and foreign devices
    # remain unquoted rather than silently becoming an RTX estimate.
    compute = await run_in_threadpool(
        local_compute,
        n_atoms,
        work,
        box_nm=box,
        resident=resident,
        devices=body.devices,
        threads=body.threads,
    )
    output = namd_run_output_bytes(
        [(s.get("steps", 0), s.get("dcd_freq", 0)) for s in work], n_atoms
    )
    local = completion_quote(
        compute,
        target="local",
        n_atoms=n_atoms,
        stages=work,
        prepared=body.prepared or bool(body.parent_job_id),
        output_bytes=output,
    )
    profile = cluster_config.load_profiles(routes_cluster._WORKSPACE_DIR).get("alpine")
    try:
        alpine = cluster_resources.recommend(
            profile,
            workspace_dir=routes_cluster._WORKSPACE_DIR,
            upload_mbps=body.upload_mbps,
            download_mbps=body.download_mbps,
            n_atoms=n_atoms,
            total_ns=sum(s.get("ns", 0) for s in work),
            stages=work,
            box_nm=box,
            partition=body.partition,
            gres_type=body.gres_type,
            prepared=body.prepared or bool(body.parent_job_id),
        )
    except ValueError as exc:
        alpine = dict(completion=dict(available=False, reason=str(exc)))
    stock = await live_stock()
    try:
        cards = runpod_select.plan_options(
            n_atoms,
            stages=work,
            box_nm=box,
            resident=resident,
            relax_ns=body.relax_ns,
            production_ns=body.production_ns,
            relax_timestep_fs=body.relax_timestep_fs,
            production_timestep_fs=body.production_timestep_fs,
            stock=stock,
            registry=runpod_select.load_rate_registry(),
            build=body.build,
            show_ineligible=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    volume = await routes_runpod._volume_info(routes_runpod._SESSION.network_volume_id)
    attach_runpod_quotes(cards, body, n_atoms, box, volume)
    return dict(
        sized=True,
        n_atoms=n_atoms,
        source=source,
        box_nm=box,
        local=local,
        alpine=alpine,
        runpod=cards,
        quoted_at=time.time(),
        live_prices=stock is not None,
    )
