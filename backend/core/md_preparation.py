"""Native preparation with automatic placement and unchanged scientific checks."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from backend.core.alpine_transfer_state import atomic_json
from backend.core.md_preparation_plan import choose_preparation, estimate_preparation


async def preparation_plan(design, body, workspace):
    from backend.core import cluster_config
    from backend.core.memory_budget import available_for_work
    # These specialized builders have different capacity checks and must not be
    # certified with the explicit DNA/solvent envelope.
    if body.protocol == 'implicit_gbis_namd' or body.graphene_nanopore or body.blade_job_id or body.vacuum_job_id or body.two_electrodes:
        return dict(ready=True, location='local', execution_target=body.execution_target,
                    detail='This specialized protocol uses its existing preparation checks; automatic remote preparation currently covers explicit-solvent DNA.')
    required, atoms = await asyncio.to_thread(estimate_preparation, design, body.model_dump())
    profile = cluster_config.load_profiles(workspace).get(body.cluster_name or 'alpine') if body.execution_target == 'alpine' else None
    plan = choose_preparation(required, available_for_work()/1024**2, body.execution_target, profile=profile)
    plan['atom_upper_bound'] = atoms
    return plan


async def prepare_for_target(prepare, design, job_dir, *, job_id, workspace, body,
                             bounded, finalize_graphene, **kwargs):
    from backend.core.md_job import MdJob
    from backend.core.namd_resources import prepare_with_memory_budget
    from backend.core.memory_budget import available_for_work, reclaim_discretionary_memory, MemoryBudgetExceeded
    from backend.core.md_preparation_finalize import finalize_package
    from backend.core import cluster_config
    from backend.core.md_preparation_remote import prepare_alpine, prepare_runpod, read_state
    job_dir = Path(job_dir)
    progress = kwargs.get('progress') or (lambda *args: None)
    if not bounded:
        # GBIS and surfaces retain their own preparation implementation/admission;
        # the explicit-DNA envelope must not certify those different systems.
        result = await asyncio.to_thread(prepare, design, job_dir, **kwargs)
        await asyncio.to_thread(finalize_package, job_dir, result[0], result[1], body, finalize_graphene)
        return result
    reclaim_discretionary_memory()
    required, atoms = await asyncio.to_thread(estimate_preparation, design, kwargs)
    profile = cluster_config.load_profiles(workspace).get(body.cluster_name or 'alpine') if body.execution_target == 'alpine' else None
    plan = choose_preparation(required, available_for_work()/1024**2, body.execution_target, profile=profile)
    plan['atom_upper_bound'] = atoms
    state = read_state(job_dir)
    if state.get('phase') in ('staging', 'running', 'fetching'):
        plan = state['plan']
    if not plan['ready']:
        raise MemoryBudgetExceeded(plan['detail'])
    if plan['location'] == 'local':
        try:
            atomic_json(job_dir / 'preparation_plan.json', plan)
            result = await asyncio.to_thread(prepare_with_memory_budget, prepare, design, job_dir, **kwargs)
            await asyncio.to_thread(finalize_package, job_dir, result[0], result[1], body, finalize_graphene)
            return result
        except MemoryBudgetExceeded:
            if body.execution_target == 'local':
                raise
            # Capacity may have changed since the preview; choose the same remote
            # target automatically, with no guard bypass or change to the model.
            plan = choose_preparation(required, 0, body.execution_target, profile=profile)
            plan['atom_upper_bound'] = atoms
    if not plan['ready']:
        raise MemoryBudgetExceeded(plan['detail'])
    atomic_json(job_dir / 'preparation_plan.json', plan)
    progress('topology', 0, plan['detail'])
    from backend.core.md_preparation_bundle import build_bundle, digest
    import cloudpickle
    payload = dict(prepare=prepare, design=design, kwargs={k:v for k,v in kwargs.items() if k != 'progress'},
                   body=body.model_dump(), graphene=finalize_graphene, bounded=bounded)
    request_digest = hashlib.sha256(cloudpickle.dumps(payload)).hexdigest()
    directory = job_dir / '.preparation'
    directory.mkdir(exist_ok=True)
    archive = directory / f'{request_digest}.tar.gz'
    if not archive.exists():
        progress('topology', 0, 'Packaging native preparation tools and frozen inputs…')
        archive_digest = await asyncio.to_thread(build_bundle, archive, payload)
    else:
        archive_digest = await asyncio.to_thread(digest, archive)
    job = MdJob.load(job_id, workspace)
    if job.user_stopped:
        raise RuntimeError('Preparation stopped by user')
    operation = prepare_alpine if plan['location'] == 'alpine' else prepare_runpod
    result = await operation(job, workspace, plan, archive, archive_digest, progress)
    return result
