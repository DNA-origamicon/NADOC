import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initNamdPegSurfaces } from './namd_peg_surfaces.js'
import { NAMD_PEG_DEFAULTS, namdPegEstimate, namdPegFormSpec } from './namd_peg_surface_model.js'

let api, ui
const findButton = text => [...document.querySelectorAll('button')].find(b => b.textContent === text)
const change = (name, value) => {
  const node = document.querySelector(`[name="${name}"]`)
  node.value = value; node.dispatchEvent(new Event('input', { bubbles: true }))
}
const record = spec => ({ spec, id: 'draft1', summary: { chains: 20, preview_sites: 2 },
  preview: { local_sites_nm: [[1, 2], [2, 3]] }, barriers: [{ message: 'Assets need validation.' }] })
beforeEach(() => {
  document.body.innerHTML = `<div id="namd-peg-surfaces"><button data-new-surface>New PEG surface…</button>
    <select></select><button data-open-surface>Open surface draft</button><p role="status"></p></div>`
  api = { listNamdPegSurfaces: vi.fn().mockResolvedValue([]),
    reviewNamdPegSurface: vi.fn(async spec => record(spec)),
    saveNamdPegSurface: vi.fn(async spec => record(spec)) }
  ui = initNamdPegSurfaces({ api })
})
afterEach(() => ui?.dispose())

it('creates a native draft, shows barriers, and preserves explicit chemistry', async () => {
  findButton('New PEG surface…').click()
  change('name', 'My support'); change('material', 'graphene'); change('repeat_units', '45')
  change('pore_diameter_nm', '3'); change('end_groups', 'OH / linker')
  findButton('Review surface').click()
  await vi.waitFor(() => expect(findButton('Create surface draft').hidden).toBe(false))
  expect(document.body.textContent).toContain('Assets need validation.')
  expect(document.body.textContent).toContain('does not create or start a simulation')
  findButton('Create surface draft').click()
  await vi.waitFor(() => expect(api.saveNamdPegSurface).toHaveBeenCalled())
  expect(api.saveNamdPegSurface.mock.calls[0]).toEqual([expect.objectContaining({ name: 'My support', repeat_units: 45,
    material: 'graphene', end_groups: 'OH / linker', pore_diameter_nm: 3 }), null])
  expect(api.saveNamdPegSurface.mock.calls[0][0]).not.toHaveProperty('oxdna_job_id')
})

it('reopens a saved surface and updates its identity', async () => {
  api.listNamdPegSurfaces.mockResolvedValue([record({ ...NAMD_PEG_DEFAULTS, name: 'Saved' })])
  await ui.refresh()
  const select = document.querySelector('#namd-peg-surfaces select'); select.value = 'draft1'; select.dispatchEvent(new Event('change'))
  findButton('Open surface draft').click()
  expect(document.querySelector('[name=name]').value).toBe('Saved')
  change('position_nm', '-5')
  findButton('Review surface').click()
  await vi.waitFor(() => expect(findButton('Save changes')).toBeTruthy())
  findButton('Save changes').click()
  await vi.waitFor(() => expect(api.saveNamdPegSurface).toHaveBeenCalledWith(expect.objectContaining({ position_nm: -5 }), 'draft1'))
})

it('keeps edits when review fails and allows retry', async () => {
  api.reviewNamdPegSurface.mockRejectedValueOnce(new Error('Review unavailable'))
  findButton('New PEG surface…').click(); change('size_nm', '30')
  findButton('Review surface').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Review unavailable'))
  expect(document.querySelector('[name=size_nm]').value).toBe('30')
  findButton('Review surface').click()
  await vi.waitFor(() => expect(findButton('Create surface draft').hidden).toBe(false))
})

it('rejects empty numbers and distinguishes segments from repeat units', () => {
  expect(namdPegEstimate(NAMD_PEG_DEFAULTS).chains).toBe(20)
  findButton('New PEG surface…').click(); change('representation', 'coarse_grained')
  change('segments', '12')
  const form = document.querySelector('.modal--namd-peg form')
  expect(namdPegFormSpec(form)).toMatchObject({ segments: 12, repeat_units: 36 })
  change('size_nm', '')
  expect(() => namdPegFormSpec(form)).toThrow('valid number')
  findButton('Review surface').click()
  expect(api.reviewNamdPegSurface).not.toHaveBeenCalled()
})

it('resumes unsaved edits after close without silently editing a saved surface', () => {
  findButton('New PEG surface…').click(); change('name', 'Unfinished')
  findButton('Close').click()
  findButton('Continue surface draft…').click()
  expect(document.querySelector('[name=name]').value).toBe('Unfinished')
})

it('does not let inactive representation fields block review', async () => {
  findButton('New PEG surface…').click()
  change('representation', 'coarse_grained'); change('segments', '')
  change('representation', 'atomistic')
  findButton('Review surface').click()
  await vi.waitFor(() => expect(api.reviewNamdPegSurface).toHaveBeenCalled())
  expect(api.reviewNamdPegSurface.mock.calls[0][0]).toMatchObject({ representation: 'atomistic', segments: 8 })
})

it('keeps a failed save editable and prevents duplicate in-flight saves', async () => {
  findButton('New PEG surface…').click(); findButton('Review surface').click()
  await vi.waitFor(() => expect(findButton('Create surface draft').hidden).toBe(false))
  let reject
  api.saveNamdPegSurface.mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
  findButton('Create surface draft').click(); findButton('Create surface draft').click()
  expect(api.saveNamdPegSurface).toHaveBeenCalledTimes(1)
  reject(new Error('Save unavailable'))
  await vi.waitFor(() => expect(document.body.textContent).toContain('Save unavailable'))
  expect(findButton('Create surface draft').disabled).toBe(false)
  findButton('Back to edit').click()
  expect(document.querySelector('[name=name]').value).toBe('PEG surface')
})
