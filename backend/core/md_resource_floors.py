"""Apply prepared memory requirements after sparse resource preferences."""
import math
import json
from pathlib import Path


def alpine_memory_floor(resources, recommended, profile):
    result = dict(resources)
    result['mem_gb'] = math.ceil(max(float(result.get('mem_gb', 0)), float(recommended['mem_gb'])))
    partition = profile.partition(result['partition'])
    if partition and partition.mem_per_core_gb:
        cores = max(int(result.get('cores', 1)), math.ceil(result['mem_gb'] / partition.mem_per_core_gb))
        resource = partition.gpu_resource(result.get('gres_type'))
        cap = resource.max_cores if resource else partition.max_cores
        if cores > cap:
            raise ValueError('Selected Alpine resource cannot provide the required host memory')
        result['cores'] = cores
    return result


def runpod_memory_floor(payloads, atoms, *, resident, package=None):
    from backend.core.namd_planning import memory_plan, prepared_stages
    memory = memory_plan(atoms, resident=resident)
    if package is not None:
        package = Path(package)
        manifest = json.loads((package / 'manifest.json').read_text())
        exact = memory_plan(atoms, resident=resident, stages=prepared_stages(package, manifest),
                            box_nm=[float(v)/10 for v in manifest['box_ang']] if manifest.get('box_ang') else None)
        memory['workflow_ram_mib'] = max(memory['workflow_ram_mib'], exact['workflow_ram_mib'])
        from backend.core.runpod_script import GPU_TYPES, VRAM_SAFETY_FRACTION
        capacity = {gpu.key: gpu.vram_mb * VRAM_SAFETY_FRACTION for gpu in GPU_TYPES}
        payloads = [p for p in payloads if any(capacity.get(gpu, 0) >= exact['gpu_mib'] for gpu in p.get('gpuTypeIds', []))]
        if not payloads:
            raise ValueError('No eligible RunPod GPU fits the prepared stage settings within the configured price limit')
    for payload in payloads:
        payload['minMemoryInGb'] = math.ceil((memory['workflow_ram_mib'] + 512) / 1024)
        payload['minVcpuCount'] = 4
    return payloads


def runpod_budget_after_preparation(job, workspace, budget):
    from backend.core.md_preparation_remote import read_state
    state = read_state(job.job_dir(workspace))
    pod_id = state.get('pod_id') if state.get('target') == 'runpod' else None
    spent = sum(float(s.get('cost_usd') or 0) for s in job.runpod_billing_sessions
                if pod_id and s.get('pod_id') == pod_id)
    return max(0.0, float(budget) - spent)
