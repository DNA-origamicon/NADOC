// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { initSimulationSubmodel } from './simulation_submodel.js'

const box = { shape: 'box', min_corner: [-2, -3, -4], max_corner: [2, 3, 4], rotation: [0, 0, 0, 1] }
function setup(api = {}) {
  document.body.innerHTML = '<div id="oxdna-submodel"></div><div id="md-submodel"></div><input type="checkbox" id="md-box-view-details">'
  let adapter
  const store = { getState: () => ({ currentDesign: { id: 'part' } }), subscribe: () => () => {} }
  const editor = { select: vi.fn(), add: vi.fn(() => edit(box)), dispose: vi.fn() }
  const saves = []
  const service = { getSimulationSubmodel: vi.fn(async () => ({ box: null })), saveSimulationSubmodel: vi.fn(async (engine, id, value) => { saves.push({engine,id,box:value}); return { box: value } }), ...api }
  const controller = initSimulationSubmodel({ document, store, api: service, createEditor: args => { adapter = args.store; return editor } })
  function edit(value) { adapter.setState({ currentDesign: { view_volumes: value ? [value] : [] } }) }
  return { controller, edit, service, saves, state: () => adapter.getState() }
}

describe('job submodel selection', () => {
  it('carries a pre-job box into a job, saves edits and restores it after switching jobs', async () => {
    const x = setup()
    document.getElementById('oxdna-define-submodel').click()
    await x.controller.created('oxdna', 'one', x.controller.capture('oxdna'))
    const moved = { ...box, min_corner: [0, 1, 2], max_corner: [4, 7, 10], rotation: [0, 0, Math.SQRT1_2, Math.SQRT1_2] }
    x.edit(moved)
    await x.controller.select('oxdna', 'two')
    expect(x.state().currentDesign.view_volumes).toEqual([])
    await x.controller.select('oxdna', 'one')
    expect(x.controller.capture('oxdna')).toEqual(moved)
    expect(x.saves.at(-1)).toEqual({engine:'oxdna',id:'one',box:moved})
    x.controller.dispose()
  })
  it('loads persisted NAMD bounds and keeps engines and drafts separate', async () => {
    const x = setup({ getSimulationSubmodel: vi.fn(async () => ({ box })) })
    await x.controller.select('md', 'namd-job')
    window.dispatchEvent(new CustomEvent('nadoc:simulation-engine', {detail:{engine:'namd'}}))
    expect(x.state().currentDesign.view_volumes[0].rotation).toEqual(box.rotation)
    await x.controller.select('md', null)
    expect(x.controller.capture('md')).toBeNull()
    expect(x.controller.capture('oxdna')).toBeNull()
    x.controller.dispose()
  })
  it('serializes writes even when selection changes during a pending save', async () => {
    let release
    const first = new Promise(resolve => { release = resolve })
    const save = vi.fn().mockReturnValueOnce(first).mockResolvedValue({ box })
    const x = setup({ saveSimulationSubmodel: save })
    await x.controller.select('oxdna', 'one')
    x.edit(box)
    x.edit({ ...box, min_corner: [-5, -5, -5] })
    await x.controller.select('oxdna', 'two')
    expect(save).toHaveBeenCalledTimes(1)
    release({box})
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(save.mock.calls.map(c => c[1])).toEqual(['one', 'one'])
    x.controller.dispose()
  })
  it('shows failed persistence and refuses editing a job whose box failed to load', async () => {
    const x = setup({ getSimulationSubmodel: vi.fn(async () => null) })
    await x.controller.select('oxdna', 'bad')
    expect(document.getElementById('oxdna-define-submodel').disabled).toBe(true)
    expect(document.body.textContent).toContain('Could not load')
    x.controller.dispose()
  })
})

it('retries the exact unsaved selection after a failed write', async () => {
  const save = vi.fn().mockResolvedValueOnce(null).mockResolvedValue({ box })
  const x = setup({ saveSimulationSubmodel: save })
  await x.controller.select('oxdna', 'one')
  x.edit(box)
  await vi.waitFor(() => expect(document.body.textContent).toContain('Could not save submodel'))
  document.querySelector('#oxdna-submodel button:nth-of-type(2)').click()
  await vi.waitFor(() => expect(document.querySelector('#oxdna-submodel [role=status]').textContent).toBe('Submodel saved to job.'))
  expect(save.mock.calls[1]).toEqual(['oxdna', 'one', box])
  x.controller.dispose()
})

it('does not let a delayed initial read erase a newly created job selection', async () => {
  let resolveRead
  const x = setup({ getSimulationSubmodel: vi.fn(() => new Promise(resolve => { resolveRead = resolve })) })
  const loading = x.controller.select('oxdna', 'new')
  await x.controller.created('oxdna', 'new', box)
  resolveRead({ box: null })
  await loading
  expect(x.controller.capture('oxdna')).toEqual(box)
  x.controller.dispose()
})

it('clears an earlier save error when a newer queued edit succeeds', async () => {
  const x = setup({ saveSimulationSubmodel: vi.fn().mockResolvedValueOnce(null).mockResolvedValue({ box }) })
  await x.controller.select('oxdna', 'one')
  x.edit(box)
  x.edit({ ...box, min_corner: [-5, -5, -5] })
  await vi.waitFor(() => expect(document.querySelector('#oxdna-submodel [role=status]').textContent).toBe('Submodel saved to job.'))
  expect(document.querySelector('#oxdna-submodel button:nth-of-type(2)').hidden).toBe(true)
  x.controller.dispose()
})

it('persists shell and visibility through resizing and job changes', async () => {
  const x = setup()
  document.getElementById('oxdna-define-submodel').click()
  const input = document.getElementById('oxdna-submodel-shell')
  expect(input.value).toBe('3')
  input.value = '0'; input.dispatchEvent(new Event('change', { bubbles: true }))
  document.getElementById('oxdna-submodel-visible').click()
  await x.controller.created('oxdna', 'one', x.controller.capture('oxdna'))
  x.edit({ ...box, max_corner: [5,6,7] })
  await x.controller.select('oxdna', 'two')
  await x.controller.select('oxdna', 'one')
  expect(x.controller.capture('oxdna')).toMatchObject({ shell_nm: 0, visible: false, max_corner: [5,6,7] })
  expect(x.state().currentDesign.view_volumes[0].outline_visible).toBe(false)
  document.getElementById('oxdna-define-submodel').click()
  expect(x.controller.capture('oxdna').visible).toBe(true)
  x.controller.dispose()
})

it('uses the NAMD master visibility and isolates shell edits from solvent settings', () => {
  const x = setup()
  const bubbled = vi.fn()
  document.body.addEventListener('change', bubbled)
  document.getElementById('md-define-submodel').click()
  const master = document.getElementById('md-box-view-details')
  expect(master.checked).toBe(true)
  bubbled.mockClear()
  const input = document.getElementById('md-submodel-shell')
  input.value = '1.5'; input.dispatchEvent(new Event('change', { bubbles: true }))
  expect(bubbled).not.toHaveBeenCalled()
  expect(x.controller.capture('md').shell_nm).toBe(1.5)
  master.click()
  expect(x.state().currentDesign.view_volumes[0].outline_visible).toBe(false)
  document.body.removeEventListener('change', bubbled)
  x.controller.dispose()
})

it('waits for box persistence before allowing Run and propagates save failures', async () => {
  let release
  const x = setup({ saveSimulationSubmodel: vi.fn(() => new Promise(resolve => { release = resolve })) })
  await x.controller.select('oxdna', 'one')
  x.edit(box)
  let flushed = false
  const pending = x.controller.flush('oxdna').then(() => { flushed = true })
  await vi.waitFor(() => expect(release).toBeTypeOf("function"))
  expect(flushed).toBe(false)
  release({box})
  await pending
  expect(flushed).toBe(true)
  x.controller.dispose()
  const failed = setup({ saveSimulationSubmodel: vi.fn(async () => null) })
  await failed.controller.select('oxdna', 'bad')
  failed.edit(box)
  await expect(failed.controller.flush('oxdna')).rejects.toThrow('Could not save')
  failed.controller.dispose()
})

it('shows native CPU budgets and ignores stale projection responses', async () => {
  let first
  const projection = { mobile_nucleotides: 14, fixed_nucleotides: 8, source_nucleotides: 84, host_ram_budget_bytes: 600 * 1048576, md_seconds: 10, mc_steps: 0 }
  const estimate = vi.fn().mockImplementationOnce(() => new Promise(resolve => { first = resolve })).mockResolvedValue({ projection })
  const x = setup({ estimateSimulationSubmodel: estimate })
  await x.controller.select('oxdna','one')
  x.edit(box)
  await vi.waitFor(() => expect(estimate).toHaveBeenCalledTimes(1))
  const radius = document.getElementById('oxdna-submodel-shell')
  radius.value = '2'; radius.dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(document.getElementById('oxdna-submodel-projection').textContent).toContain('14 mobile + 8 fixed'))
  first({projection:{...projection,mobile_nucleotides:999}})
  await Promise.resolve()
  expect(document.getElementById('oxdna-submodel-projection').textContent).toContain('simulation VRAM 0 MiB')
  expect(document.getElementById('oxdna-submodel-projection').textContent).not.toContain('999')
  x.controller.dispose()
})
