// @vitest-environment jsdom
/**
 * Factory contract for the wizard's SLURM resource block.
 *
 * The load-bearing behaviours: it sizes the request against the SELECTED node without
 * being asked, it shows those numbers as the values (not as ghost placeholders), and it
 * sends only what the user changed — an untouched field must stay auto so the backend
 * can re-derive it from the built package's exact atom count.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { initWizardResources } from './md_job_wizard_resources.js'

const SIZING = {
  sized: true,
  n_atoms: 623_400,
  n_atoms_source: 'estimated',
  total_ns: 12,
  resources: {
    partition: 'ah200', kind: 'gpu', gpus: 1, cores: 8, mem_gb: 52,
    walltime: '10:00:00', qos: 'normal', expected_ns_per_day: 28.75,
    est_cost_su: 1240.4, safety_factor: 1.5, notes: [],
  },
  available_qos: [{ name: 'normal', max_walltime_h: 24 }, { name: 'long', max_walltime_h: 168 }],
}

function setup({ partition = 'ah200', totalNs = 12, preview = SIZING } = {}) {
  document.body.innerHTML = '<div id="mount"></div>'
  const mount = document.getElementById('mount')
  const getSlurmPreview = vi.fn(async () => preview)
  const onChange = vi.fn()
  let _partition = partition
  const res = initWizardResources({
    mount, getSlurmPreview, onChange,
    getPartition: () => _partition,
    getTotalNs: () => totalNs,
  })
  return { res, mount, getSlurmPreview, onChange, setPartition: p => { _partition = p } }
}

const field = (mount, key) => mount.querySelector(`[data-res="${key}"]`)

beforeEach(() => { document.body.innerHTML = '' })

describe('sizing', () => {
  it('asks the backend to size THIS design on the selected node', async () => {
    const { res, getSlurmPreview } = setup()
    await res.refresh()
    expect(getSlurmPreview).toHaveBeenCalledWith({
      cluster_name: 'alpine', partition: 'ah200', total_ns: 12, job_name: 'nadoc_job',
    })
  })

  it('autopopulates cores and wall time from the recommendation', async () => {
    const { res, mount } = setup()
    await res.refresh()
    expect(field(mount, 'cores').value).toBe('8')
    expect(field(mount, 'walltime').value).toBe('10:00:00')
    expect(field(mount, 'mem_gb').value).toBe('52')
    expect(mount.textContent).toContain('623,400 atoms')
  })

  it('re-sizes when the node changes and not when nothing moved', async () => {
    // The atom estimate behind this builds the design's whole heavy-atom model the first
    // time, so a repeat call for an unchanged (partition, length) pair is not free.
    const { res, getSlurmPreview, setPartition } = setup()
    await res.refresh()
    await res.refresh()
    expect(getSlurmPreview).toHaveBeenCalledTimes(1)
    setPartition('aa100')
    await res.refresh()
    expect(getSlurmPreview).toHaveBeenCalledTimes(2)
    expect(getSlurmPreview.mock.calls[1][0].partition).toBe('aa100')
  })

  it('asks for nothing until a node is picked', async () => {
    const { res, mount, getSlurmPreview } = setup({ partition: null })
    await res.refresh()
    expect(getSlurmPreview).not.toHaveBeenCalled()
    expect(mount.textContent).toContain('Pick a node above')
  })

  it('says so, and stays submittable, when sizing fails', async () => {
    const { res, mount } = setup({ preview: { sized: false, reason: 'No design loaded.' } })
    await res.refresh()
    expect(mount.textContent).toContain('No design loaded.')
    expect(res.overrides()).toEqual({})
  })
})

describe('overrides', () => {
  it('sends nothing when the recommendation is accepted as-is', async () => {
    // Not "sends the shown values": the wizard sizes against an ESTIMATED atom count, so
    // an untouched field must be left for the backend to re-derive from the real package.
    const { res } = setup()
    await res.refresh()
    expect(res.overrides()).toEqual({})
  })

  it('sends only what was edited, with numbers coerced', async () => {
    const { res, mount } = setup()
    await res.refresh()
    field(mount, 'walltime').value = '48:00:00'
    field(mount, 'walltime').dispatchEvent(new Event('input'))
    field(mount, 'cores').value = '16'
    field(mount, 'cores').dispatchEvent(new Event('input'))
    expect(res.overrides()).toEqual({ walltime: '48:00:00', cores: 16 })
  })

  it('clearing a field hands it back to the recommendation', async () => {
    const { res, mount } = setup()
    await res.refresh()
    const cores = field(mount, 'cores')
    cores.value = '16'
    cores.dispatchEvent(new Event('input'))
    cores.value = ''
    cores.dispatchEvent(new Event('input'))
    expect(res.overrides()).toEqual({})
  })

  it('keeps an explicit wall time across a re-size', async () => {
    // An explicit 48 h is a decision about this run, not about whichever node happened
    // to be selected when it was typed.
    const { res, mount, setPartition } = setup()
    await res.refresh()
    field(mount, 'walltime').value = '48:00:00'
    field(mount, 'walltime').dispatchEvent(new Event('input'))
    setPartition('aa100')
    await res.refresh()
    expect(res.overrides()).toEqual({ walltime: '48:00:00' })
    expect(field(mount, 'walltime').value).toBe('48:00:00')
  })

  it('reset drops every edit', async () => {
    const { res, mount } = setup()
    await res.refresh()
    field(mount, 'cores').value = '16'
    field(mount, 'cores').dispatchEvent(new Event('change'))
    mount.querySelector('#wiz-res-reset').click()
    expect(res.overrides()).toEqual({})
    expect(field(mount, 'cores').value).toBe('8')
  })

  it('notifies the wizard on every edit so the payload never lags', async () => {
    const { res, mount, onChange } = setup()
    await res.refresh()
    onChange.mockClear()
    field(mount, 'cores').value = '16'
    field(mount, 'cores').dispatchEvent(new Event('input'))
    expect(onChange).toHaveBeenCalled()
  })
})
