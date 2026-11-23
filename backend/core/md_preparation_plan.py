"""Choose preparation capacity independently of the simulation execution device."""
from __future__ import annotations

import math


def choose_preparation(required_mib, available_mib, target, *, profile=None):
    if not math.isfinite(required_mib) or required_mib <= 0:
        raise ValueError('Cannot establish preparation memory requirements')
    if target not in ('local', 'alpine', 'runpod'):
        raise ValueError('Unknown preparation target')
    plan = dict(required_mib=math.ceil(required_mib), available_local_mib=max(0, int(available_mib)),
                execution_target=target, location='local', ready=True)
    if required_mib <= available_mib:
        plan['detail'] = 'NADOC will prepare this job locally, then run it on the selected target.'
        return plan
    if target == 'local':
        plan.update(ready=False, detail='There is not enough available desktop RAM to prepare this job. '
                    'Choose Alpine or RunPod to prepare and run remotely, or free desktop memory.')
        return plan
    # The admission envelope is additional RAM. Include the same 4 GiB system
    # reserve plus worker/import overhead in the remote allocation, not just RSS.
    memory_gb = math.ceil((required_mib + 4096 + 1024) / 1024)
    plan.update(location=target, mem_gb=memory_gb, cores=4, walltime='02:00:00')
    if target == 'alpine':
        if profile is None:
            raise ValueError('Alpine profile is unavailable')
        candidates = []
        for partition in profile.partitions:
            per_core = partition.mem_per_core_gb
            if partition.kind != 'cpu' or not per_core:
                continue
            cores = max(4, math.ceil(memory_gb / per_core))
            if cores <= partition.max_cores and partition.allowed_qos:
                candidates.append((cores, partition.name, partition.allowed_qos[0]))
        if not candidates:
            plan.update(ready=False, detail='No configured Alpine CPU partition has enough preparation RAM.')
            return plan
        cores, partition, qos = min(candidates, key=lambda x: (x[1] != 'acpu', x[0]))
        plan.update(cores=cores, partition=partition, qos=qos)
    plan['detail'] = f"NADOC will prepare this job on {'RunPod' if target == 'runpod' else target.title()} automatically ({memory_gb} GiB RAM)."
    return plan


def estimate_preparation(design, kwargs):
    from backend.core.md_vram import estimate_profile_from_design
    from backend.core.namd_resources import preparation_memory_mib
    screening = kwargs.get('salt_mode') == 'screening'
    profile = estimate_profile_from_design(
        design, padding_nm=kwargs.get('padding_nm', 6), box_mode=kwargs.get('box_mode', 'rotation'),
        box_size_nm=kwargs.get('box_size_nm'), atomistic_model=kwargs.get('atomistic_model'),
        nacl_mM=0 if screening else kwargs.get('ion_conc_mM', 0),
        mgcl2_mM=12.5 if screening else kwargs.get('mg_conc_mM', 12.5))
    if not profile or not math.isfinite(profile.get('atom_upper_bound', 0)) or profile['atom_upper_bound'] <= 0:
        raise ValueError('Cannot establish preparation memory requirements')
    return preparation_memory_mib(profile['atom_upper_bound']), profile['atom_upper_bound']
