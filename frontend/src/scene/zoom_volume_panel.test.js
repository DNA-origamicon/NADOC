import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initZoomVolume } from './zoom_volume.js'

let panel
const listeners = new Set(), frames = new Set()
function setup(assembly = false) {
  document.body.innerHTML = '<div id="right-tab-content-visualization"></div>'
  let state = { currentDesign: { id: 'part' }, assemblyActive: assembly, currentAssembly: { id: 'assembly' }, selection: { items: [{ kind: 'strand', id: 's1' }] }, activeInstanceId: 'i1' }
  const store = { getState: () => state, subscribe: cb => { listeners.add(cb); return () => listeners.delete(cb) } }
  panel = initZoomVolume({ document, scene: new THREE.Scene(), canvas: document.createElement('canvas'), store,
    designRenderer: {}, assemblyRenderer: {}, addFrameCallback: cb => frames.add(cb), removeFrameCallback: cb => frames.delete(cb) })
  return patch => { const previous = state; state = { ...state, ...patch }; for (const cb of [...listeners]) cb(state, previous) }
}
afterEach(() => { panel?.dispose(); panel = null; expect(listeners.size).toBe(0); expect(frames.size).toBe(0); vi.restoreAllMocks(); document.body.replaceChildren() })

it('adds independent selections, settings and insets, replaces one selection, and deletes only that entry', () => {
  const update = setup()
  const first = panel.capture()
  update({ selection: { items: [{ kind: 'strand', id: 's2' }] } })
  panel.capture()
  const rows = document.querySelectorAll('.zoom-volume-row')
  expect(rows).toHaveLength(2)
  expect(document.querySelectorAll('.zoom-volume-inset')).toHaveLength(2)
  const control = (i, key) => rows[i].querySelector(`[data-control="${key}"]`)
  control(0, 'representation').value = 'beads'; control(0, 'representation').dispatchEvent(new Event('change'))
  expect(control(1, 'representation').value).not.toBe('beads')
  control(0, 'enabled').click()
  expect(control(0, 'enabled').getAttribute('aria-pressed')).toBe('false')
  expect(control(1, 'enabled').getAttribute('aria-pressed')).toBe('true')
  control(0, 'box').click()
  expect(control(1, 'box').getAttribute('aria-pressed')).toBe('true')
  expect(panel.debug().entries.map(e => e.targets[0].refs[0].id)).toEqual(['s1', 's2'])
  update({ selection: { items: [{ kind: 'strand', id: 's3' }] } })
  control(0, 'set').click()
  expect(panel.debug().entries.map(e => e.targets[0].refs[0].id)).toEqual(['s3', 's2'])
  control(0, 'delete').click()
  expect(panel.debug().entries).toHaveLength(1)
  expect(panel.debug().entries[0].id).not.toBe(first)
  expect(document.querySelectorAll('.zoom-volume-inset')).toHaveLength(1)
  expect(frames.size).toBe(1)
})

it('rejects empty additions and preserves an existing selection on an empty replacement', () => {
  const update = setup(); panel.capture()
  update({ selection: { items: [] } })
  expect(panel.capture()).toBeNull()
  document.querySelector('[data-control="set"]').click()
  expect(panel.debug().entries[0].targets[0].refs[0].id).toBe('s1')
  expect(document.querySelectorAll('.zoom-volume-row')).toHaveLength(1)
  expect(frames.size).toBe(1)
})

it('supports assembly selections, master toggles and clears all entries when switching documents', () => {
  const update = setup(true); panel.capture()
  update({ activeInstanceId: 'i2' }); panel.capture()
  expect(panel.debug().entries.map(e => e.targets[0].instanceId)).toEqual(['i1', 'i2'])
  document.getElementById('zoom-volume-enable-all').click()
  expect([...document.querySelectorAll('[data-control="enabled"]')].map(b => b.getAttribute('aria-pressed'))).toEqual(['false', 'false'])
  document.getElementById('zoom-volume-enable-all').click()
  expect([...document.querySelectorAll('[data-control="enabled"]')].map(b => b.getAttribute('aria-pressed'))).toEqual(['true', 'true'])
  document.getElementById('zoom-volume-toggle-all').click()
  expect([...document.querySelectorAll('[data-control="box"]')].map(b => b.getAttribute('aria-pressed'))).toEqual(['false', 'false'])
  update({ currentAssembly: { id: 'another' } })
  expect(panel.debug().entries).toEqual([])
  expect(document.querySelectorAll('.zoom-volume-inset')).toHaveLength(0)
  expect(frames.size).toBe(0)
})

it('keeps zoom factors independent and clamps both ends without changing selections', () => {
  setup(); panel.capture(); panel.capture()
  const groups = document.querySelectorAll('.zoom-volume-zoom-controls')
  const [plus, minus] = groups[0].querySelectorAll('button')
  const original = panel.debug().entries.map(e => e.targets)
  plus.click()
  groups[1].querySelectorAll('button')[1].click()
  expect(panel.debug().entries.map(e => e.zoom)).toEqual([1.25, .8])
  for (let i = 0; i < 20; i++) plus.click()
  expect(panel.debug().entries[0].zoom).toBe(1.25 ** 8)
  for (let i = 0; i < 30; i++) minus.click()
  expect(panel.debug().entries[0].zoom).toBe(1.25 ** -8)
  expect(panel.debug().entries.map(e => e.targets)).toEqual(original)
  document.querySelector('[data-control="delete"]').click()
  expect(document.querySelectorAll('.zoom-volume-zoom-controls')).toHaveLength(1)
  expect(panel.debug().entries[0].zoom).toBe(.8)
})

it('updates one dedicated submodel entry without retargeting other insets', () => {
  setup(); panel.capture()
  const box = { min_corner: [0, 0, 0], max_corner: [10, 10, 10] }
  window.dispatchEvent(new CustomEvent('nadoc:zoom-volume-box', { detail: box }))
  expect(panel.debug().entries).toHaveLength(2)
  expect(panel.debug().entries[0].targets[0].refs[0].id).toBe('s1')
  box.min_corner[0] = 2
  expect(panel.debug().entries[1].volume.min_corner[0]).toBe(0)
  window.dispatchEvent(new CustomEvent('nadoc:zoom-volume-box', { detail: box }))
  expect(panel.debug().entries).toHaveLength(2)
  expect(panel.debug().entries[1].volume.min_corner[0]).toBe(2)
  expect(panel.setBox({ min_corner: [0,0,0], max_corner: [0,0,0] })).toBe(false)
  expect(panel.debug().entries[1].volume.min_corner[0]).toBe(2)
  panel.dispose(); panel = null
  window.dispatchEvent(new CustomEvent('nadoc:zoom-volume-box', { detail: box }))
  expect(document.querySelectorAll('.zoom-volume-inset')).toHaveLength(0)
})
