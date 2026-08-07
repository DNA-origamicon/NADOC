import { describe, it, expect } from 'vitest'
import {
  availabilityBadge,
  availabilityHeader,
  availabilityMessage,
  availabilityView,
  bestPartitionHint,
  formatHours,
  formatSu,
  formatWait,
  renderAvailabilityRows,
} from './cluster_availability_rows.js'

const row = (over = {}) => ({
  partition: 'ah200',
  gpu_model: 'NVIDIA H200',
  gres_type: 'h200',
  gpus_total: 8,
  gpus_free: 7,
  nodes_total: 2,
  nodes_idle: 1,
  nodes_mixed: 1,
  nodes_alloc: 0,
  pending_jobs: 2,
  pending_gpus: 3,
  top_reason: 'Priority (1)',
  wait_min: 120,
  wait_basis: 'SLURM backfill estimate',
  max_walltime_h: 24,
  ...over,
})

describe('formatWait', () => {
  it('minutes / hours / days by magnitude', () => {
    expect(formatWait(0)).toBe('now')
    expect(formatWait(45)).toBe('45 min')
    expect(formatWait(200)).toBe('3 h 20 m')
    expect(formatWait(180)).toBe('3 h')
    expect(formatWait(2880)).toBe('2 d')
  })

  it('an absent estimate is "unknown", never "now"', () => {
    // The whole point of the popup: SLURM failing to place a job must not read as
    // an immediate start.
    expect(formatWait(null)).toBe('unknown')
    expect(formatWait(undefined)).toBe('unknown')
    expect(formatWait(Infinity)).toBe('unknown')
  })
})

describe('formatHours', () => {
  it('minutes / hours / days by magnitude', () => {
    expect(formatHours(0.5)).toBe('30 min')
    expect(formatHours(5.4)).toBe('5.4 h')
    expect(formatHours(72)).toBe('3.0 d')
    expect(formatHours(null)).toBe('—')
  })
})

describe('formatSu', () => {
  it('scales the unit with the magnitude', () => {
    expect(formatSu(4.25)).toBe('4.3 SU')
    expect(formatSu(842.6)).toBe('843 SU')
    expect(formatSu(250_000)).toBe('250k SU')
    expect(formatSu(null)).toBe('—')
  })
})

describe('availabilityBadge', () => {
  it('free only when nothing is queued ahead', () => {
    expect(availabilityBadge(row({ pending_gpus: 0 })).text).toBe('free')
    expect(availabilityBadge(row({ pending_gpus: 3 })).text).toBe('contended')
    expect(availabilityBadge(row({ gpus_free: 0 })).text).toBe('full')
  })

  it('request-only hardware gets its own badge', () => {
    expect(availabilityBadge({ request_only: true }).text).toBe('request-only')
  })
})

describe('availabilityView', () => {
  it('maps the backend row onto display fields', () => {
    const v = availabilityView(row())
    expect(v.partition).toBe('ah200')
    expect(v.gpu).toBe('NVIDIA H200')
    expect(v.free).toBe('7 / 8')
    expect(v.nodes).toBe('1 idle · 1 partial · 0 busy')
    expect(v.pending).toBe('2 jobs (3 GPU)')
    expect(v.wait).toBe('2 h')
    expect(v.maxWall).toBe('24 h')
  })

  it('singularises one pending job and says "none" for an empty queue', () => {
    expect(availabilityView(row({ pending_jobs: 1, pending_gpus: 1 })).pending)
      .toBe('1 job (1 GPU)')
    expect(availabilityView(row({ pending_jobs: 0 })).pending).toBe('none')
  })

  it('falls back to the gres token when no model name is given', () => {
    expect(availabilityView(row({ gpu_model: '' })).gpu).toBe('h200')
  })

  it('request-only rows show access, not a wait', () => {
    const v = availabilityView({ partition: 'gh200', request_only: true, nodes_total: 2 })
    expect(v.wait).toBe('request access')
    expect(v.free).toBe('—')
  })
})

describe('renderAvailabilityRows', () => {
  it('renders one row per partition with its name and free count', () => {
    const html = renderAvailabilityRows([row(), row({ partition: 'aa100', gpus_free: 0 })])
    expect(html).toContain('data-partition="ah200"')
    expect(html).toContain('data-partition="aa100"')
    expect(html).toContain('7 / 8')
  })

  it('exposes the wait provenance as a tooltip', () => {
    expect(renderAvailabilityRows([row()])).toContain('title="SLURM backfill estimate"')
  })

  it('dims request-only rows', () => {
    const html = renderAvailabilityRows([{ partition: 'gh200', request_only: true }])
    expect(html).toContain('opacity:.55')
  })

  it('escapes partition text rather than injecting markup', () => {
    const html = renderAvailabilityRows([row({ partition: '<img src=x>' })])
    expect(html).not.toContain('<img src=x>')
    expect(html).toContain('&lt;img src=x&gt;')
  })

  it('returns empty string for no rows', () => {
    expect(renderAvailabilityRows([])).toBe('')
    expect(renderAvailabilityRows(null)).toBe('')
  })
})

describe('availabilityHeader', () => {
  it('names the columns the table renders', () => {
    const h = availabilityHeader()
    expect(h).toContain('Partition')
    expect(h).toContain('Est. wait')
    expect(h).toContain('Done in')
  })
})

describe('availabilityMessage', () => {
  it('prompts before the first check', () => {
    expect(availabilityMessage(null)).toMatch(/GPU availability/)
  })

  it('busy and error states win over the response', () => {
    expect(availabilityMessage(null, { busy: true })).toBe('Querying Alpine…')
    expect(availabilityMessage({ partitions: [row()] }, { error: 'boom' })).toBe('boom')
  })

  it('states provenance: when it was checked and what the history covers', () => {
    const msg = availabilityMessage({
      partitions: [row()], checked_at: '2026-08-06T12:00:00',
      history_days: 30, history_scope: 'cluster-wide', job_shape: { n_atoms: 1 },
    })
    expect(msg).toContain('checked 2026-08-06 12:00:00')
    expect(msg).toContain('last 30 d, cluster-wide')
  })

  it('says the cost columns are blank when no job is selected', () => {
    const msg = availabilityMessage({ partitions: [row()], history_scope: 'cluster-wide', history_days: 30 })
    expect(msg).toContain('no job selected')
  })

  it('surfaces probe warnings', () => {
    const msg = availabilityMessage({ partitions: [row()], warnings: ['timed out: sacct'] })
    expect(msg).toContain('timed out: sacct')
  })
})

describe('bestPartitionHint', () => {
  it('picks the partition that FINISHES first, not the one that starts first', () => {
    const hint = bestPartitionHint([
      row({ partition: 'aa100', wait_min: 0, time_to_result_h: 40, job_cost_su: 900 }),
      row({ partition: 'ah200', wait_min: 120, time_to_result_h: 18, job_cost_su: 2000 }),
    ])
    expect(hint).toContain('ah200')
    expect(hint).toContain('done in 18.0 h')
  })

  it('ignores rows with no estimate rather than treating them as instant', () => {
    const hint = bestPartitionHint([
      row({ partition: 'ah200', wait_min: null, time_to_result_h: null }),
      row({ partition: 'aa100', wait_min: 60, time_to_result_h: 30 }),
    ])
    expect(hint).toContain('aa100')
  })

  it('ignores request-only hardware', () => {
    expect(bestPartitionHint([{ partition: 'gh200', request_only: true, time_to_result_h: 1 }])).toBe('')
  })

  it('returns empty when nothing is projectable', () => {
    expect(bestPartitionHint([])).toBe('')
    expect(bestPartitionHint([row({ time_to_result_h: null })])).toBe('')
  })
})

describe('MIG slices', () => {
  it('are reported apart from whole cards, never folded into them', () => {
    // A whole-GPU job cannot use a 35 GB slice, so adding them would advertise
    // capacity the job can never get (live 2026-08-06: 8 nodes read as 56 "GPUs").
    const v = availabilityView(row({ gpus_free: 9, gpus_total: 10, mig_free: 6, mig_total: 6 }))
    expect(v.free).toBe('9 / 10')
    expect(v.mig).toBe('+6/6 MIG')
  })

  it('are omitted entirely on partitions without MIG', () => {
    expect(availabilityView(row({ mig_total: 0 })).mig).toBe('')
  })

  it('render as a separate sub-line flagged as unusable by a whole-GPU job', () => {
    const html = renderAvailabilityRows([row({ mig_free: 6, mig_total: 6 })])
    expect(html).toContain('+6/6 MIG')
    expect(html).toContain('whole-GPU job cannot use')
  })
})

describe('node breakdown', () => {
  it('names drained nodes so missing capacity is explained', () => {
    const v = availabilityView(row({ nodes_idle: 2, nodes_mixed: 2, nodes_alloc: 0, nodes_down: 4 }))
    expect(v.nodes).toBe('2 idle · 2 partial · 0 busy · 4 down')
  })

  it('omits the down count when every node is healthy', () => {
    expect(availabilityView(row({ nodes_down: 0 })).nodes).not.toContain('down')
  })
})
