import { describe, it, expect } from 'vitest'
import {
  TARGETS, TARGET_IDS, UNWIRED_TARGETS,
  atomCapLabel, defaultPartition, localGpuSpeedFactor, localHardwareSummary,
  partitionChoices, relativeSpeedLabel, renderSlurmDetails, slurmFacts,
  targetPayloadFields, targetReadiness,
} from './md_job_wizard_target_model.js'

describe('TARGETS', () => {
  it('offers exactly the three compute targets, local first', () => {
    expect(TARGET_IDS).toEqual(['local', 'alpine', 'runpod'])
    expect(TARGETS[0].label).toBe('This computer')
  })
})

describe('localGpuSpeedFactor', () => {
  it('matches decorated vendor names', () => {
    expect(localGpuSpeedFactor('NVIDIA GeForce RTX 4090')).toBe(1.1)
    expect(localGpuSpeedFactor('NVIDIA A100-SXM4-80GB')).toBe(1.0)
    expect(localGpuSpeedFactor('Tesla V100-PCIE-16GB')).toBe(0.45)
  })

  it('returns null — not 1.0 — for an unrecognised card', () => {
    // 1.0 would silently assert "exactly A100-equivalent" and put a confident wrong
    // number beside every partition in the comparison.
    expect(localGpuSpeedFactor('Intel Arc B580')).toBeNull()
    expect(localGpuSpeedFactor('')).toBeNull()
    expect(localGpuSpeedFactor(undefined)).toBeNull()
  })

  it('prefers the more specific key when names overlap', () => {
    // "RTX Pro 6000" must not fall through to a bare digit match. 2.5 not 1.6:
    // measured equal to the H200 head-to-head on Alpine (2026-08-07).
    expect(localGpuSpeedFactor('NVIDIA RTX Pro 6000 Blackwell')).toBe(2.5)
  })
})

describe('relativeSpeedLabel', () => {
  it('reads as a multiple of this computer when the cluster is faster', () => {
    expect(relativeSpeedLabel(2.5, 1.0)).toBe('≈2.5× this computer')
    expect(relativeSpeedLabel(1.6, 0.65)).toBe('≈2.5× this computer')
  })

  it('inverts the ratio rather than showing a fraction when slower', () => {
    expect(relativeSpeedLabel(0.5, 1.0)).toBe('≈2.0× slower than this computer')
  })

  it('says nothing when there is no local baseline', () => {
    expect(relativeSpeedLabel(2.5, null)).toBe('')
    expect(relativeSpeedLabel(2.5, 0)).toBe('')
    expect(relativeSpeedLabel(null, 1.0)).toBe('')
  })
})

describe('localHardwareSummary / atomCapLabel', () => {
  it('prefers the backend pre-joined summary', () => {
    expect(localHardwareSummary({ summary: 'RTX 4090 · 24 GB VRAM' })).toBe('RTX 4090 · 24 GB VRAM')
  })

  it('assembles one from parts when the summary is missing', () => {
    expect(localHardwareSummary({ gpu_name: 'RTX 4090', vram_mb: 24576, host_ram_mb: 65536, physical_cores: 16 }))
      .toBe('RTX 4090 · 24 GB VRAM · 64 GB RAM · 16 cores')
  })

  it('is empty for no probe at all', () => {
    expect(localHardwareSummary(null)).toBe('')
  })

  it('scales the atom cap unit', () => {
    expect(atomCapLabel({ atom_cap: 2_400_000 })).toContain('2.4M atoms')
    expect(atomCapLabel({ atom_cap: 350_000 })).toContain('350k atoms')
    expect(atomCapLabel({})).toBe('')
  })
})

describe('targetReadiness', () => {
  it('local is always ready', () => {
    expect(targetReadiness('local')).toEqual({ ready: true, reason: '' })
  })

  it('alpine needs BOTH a session and a chosen partition', () => {
    // Letting the user past either gate would surface the failure only after the whole
    // protocol is configured and the package built.
    expect(targetReadiness('alpine', { clusterState: 'disconnected' }).ready).toBe(false)
    expect(targetReadiness('alpine', { clusterState: 'connected', partition: null }).ready).toBe(false)
    expect(targetReadiness('alpine', { clusterState: 'connected', partition: 'ah200' }))
      .toEqual({ ready: true, reason: '' })
  })

  it('gives an actionable reason, not just false', () => {
    expect(targetReadiness('alpine', { clusterState: 'disconnected' }).reason).toMatch(/Sign in/)
    expect(targetReadiness('alpine', { clusterState: 'connected' }).reason).toMatch(/partition/)
  })

  it('blocks unwired targets with their own reason', () => {
    const r = targetReadiness('runpod')
    expect(r.ready).toBe(false)
    expect(r.reason).toBe(UNWIRED_TARGETS.runpod)
  })

  it('blocks an unknown target', () => {
    expect(targetReadiness('nonsense').ready).toBe(false)
  })
})

describe('targetPayloadFields', () => {
  it('local carries no cluster fields', () => {
    expect(targetPayloadFields('local')).toEqual({
      execution_target: 'local', cluster_name: null, partition: null, runpod_gpu_key: null,
    })
  })

  it('alpine carries the cluster and the chosen partition', () => {
    expect(targetPayloadFields('alpine', { partition: 'ah200' })).toEqual({
      execution_target: 'alpine', cluster_name: 'alpine', partition: 'ah200', runpod_gpu_key: null,
    })
  })

  it('clears a stale partition when the target is not alpine', () => {
    // A leftover partition on a local job would resurface at submit time.
    expect(targetPayloadFields('local', { partition: 'ah200' }).partition).toBeNull()
  })

  it('falls back to local for an unknown target', () => {
    expect(targetPayloadFields('nonsense').execution_target).toBe('local')
  })
})

const AVAIL = {
  partitions: [
    { partition: 'ah200', gpu_model: 'NVIDIA H200', gpus_free: 6, gpus_total: 16,
      mig_free: 25, mig_total: 40, wait_label: '~0 min', wait_basis: 'free now',
      speed_factor: 2.5, max_walltime_h: 24 },
    { partition: 'aa100', gpu_model: 'NVIDIA A100', gpus_free: 0, gpus_total: 30,
      wait_label: '13 d 16 h', wait_basis: 'SLURM backfill estimate',
      speed_factor: 1.0, max_walltime_h: 24 },
    { partition: 'gh200', gpu_model: 'NVIDIA Grace-Hopper', request_only: true,
      gpus_total: 2, gpus_free: 0 },
  ],
}

describe('partitionChoices', () => {
  it('maps each partition to a selectable row with a speed comparison', () => {
    const rows = partitionChoices(AVAIL, 0.65)          // local ≈ RTX 3090
    expect(rows[0].partition).toBe('ah200')
    expect(rows[0].free).toBe('6 / 16')
    expect(rows[0].wait).toBe('~0 min')
    expect(rows[0].speed).toBe('≈3.8× this computer')
    expect(rows[0].selectable).toBe(true)
  })

  it('flags MIG slices as unusable rather than adding them to the free count', () => {
    const rows = partitionChoices(AVAIL, 1.0)
    expect(rows[0].free).toBe('6 / 16')
    expect(rows[0].migNote).toMatch(/25 MIG slices \(not usable/)
    expect(rows[1].migNote).toBe('')
  })

  it('keeps request-only hardware visible but unselectable', () => {
    const gh = partitionChoices(AVAIL, 1.0).find(r => r.partition === 'gh200')
    expect(gh.selectable).toBe(false)
    expect(gh.wait).toBe('request access')
    expect(gh.note).toMatch(/support request/)
  })

  it('omits the speed column when the local card is unknown', () => {
    expect(partitionChoices(AVAIL, null)[0].speed).toBe('')
  })

  it('is empty for a missing response', () => {
    expect(partitionChoices(null)).toEqual([])
    expect(partitionChoices({})).toEqual([])
  })
})

describe('defaultPartition', () => {
  it('picks the first SELECTABLE row — the backend already ranked by time-to-result', () => {
    expect(defaultPartition(partitionChoices(AVAIL, 1.0))).toBe('ah200')
  })

  it('never auto-picks request-only hardware', () => {
    const onlyGh = partitionChoices({ partitions: [AVAIL.partitions[2]] }, 1.0)
    expect(defaultPartition(onlyGh)).toBeNull()
  })

  it('is null for no choices', () => {
    expect(defaultPartition([])).toBeNull()
    expect(defaultPartition(null)).toBeNull()
  })
})

const PREVIEW = {
  sized: true,
  n_atoms: 62673,
  n_atoms_source: 'estimated',
  resources: {
    partition: 'ah200', gres_type: 'h200', qos: 'gpu-long', walltime: '62:14:27',
    cores: 8, gpus: 1, mem_gb: 10, expected_ns_per_day: 115.68, measured: false,
    est_cost_su: 21286.3,
  },
  directives: ['#SBATCH --partition=ah200', '#SBATCH --gres=gpu:h200:1'],
  modules: ['gcc/14.2.0', 'namd/3.0.1_gpu'],
  exec_line: 'namd3 +p8 +setcpuaffinity +devices 0 <stage>.conf > output/<stage>.log 2>&1',
  warnings: [],
  text: '#!/bin/bash\n#SBATCH --partition=ah200\nmodule load gcc/14.2.0 namd/3.0.1_gpu',
}

describe('slurmFacts', () => {
  it('names every field that decides what SLURM will do', () => {
    const labels = slurmFacts(PREVIEW).map(([k]) => k)
    expect(labels).toEqual(['Partition', 'QoS', 'Walltime', 'CPUs / GPUs', 'Memory',
                            'Throughput', 'Est. cost', 'System size'])
  })

  it('shows the GRES token beside the partition — SLURM rejects an untyped request', () => {
    const facts = Object.fromEntries(slurmFacts(PREVIEW))
    expect(facts.Partition).toBe('ah200 (h200)')
    expect(facts['CPUs / GPUs']).toBe('8 cores · 1 GPU')
    expect(facts['Est. cost']).toBe('21,286 SU')
  })

  it('says whether the throughput is measured or a guess', () => {
    expect(Object.fromEntries(slurmFacts(PREVIEW)).Throughput).toContain('(estimated)')
    const measured = { ...PREVIEW, resources: { ...PREVIEW.resources, measured: true } }
    expect(Object.fromEntries(slurmFacts(measured)).Throughput).toContain('(measured)')
  })

  it('flags an atom count that is a pre-solvation estimate', () => {
    expect(Object.fromEntries(slurmFacts(PREVIEW))['System size'])
      .toBe('62,673 atoms (estimated — solvation not run yet)')
  })

  it('is empty without a sized response', () => {
    expect(slurmFacts(null)).toEqual([])
    expect(slurmFacts({})).toEqual([])
  })
})

describe('renderSlurmDetails', () => {
  it('renders the facts and the literal sbatch text', () => {
    const html = renderSlurmDetails(PREVIEW)
    expect(html).toContain('ah200 (h200)')
    expect(html).toContain('gpu-long')
    expect(html).toContain('#SBATCH --partition=ah200')
    expect(html).toContain('namd/3.0.1_gpu')
  })

  it('surfaces a clamped walltime as a warning, not a silent number', () => {
    // A capped walltime is not a slower run — it cannot finish in one submission.
    const html = renderSlurmDetails({ ...PREVIEW,
      warnings: ['Walltime is capped at the gpu-long ceiling (168 h).'] })
    expect(html).toContain('Walltime is capped')
    expect(html).toContain('⚠')
  })

  it('shows busy and error states instead of a stale table', () => {
    expect(renderSlurmDetails(null, { busy: true })).toContain('Sizing the SLURM request')
    expect(renderSlurmDetails(PREVIEW, { error: 'nope' })).toContain('nope')
  })

  it('explains an unsized response rather than rendering blank', () => {
    const html = renderSlurmDetails({ sized: false, reason: 'No design loaded.' })
    expect(html).toContain('No design loaded.')
  })

  it('renders nothing at all when there is no preview', () => {
    expect(renderSlurmDetails(null)).toBe('')
  })

  it('escapes the script text rather than injecting it', () => {
    const html = renderSlurmDetails({ ...PREVIEW, text: '<script>x</script>' })
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
