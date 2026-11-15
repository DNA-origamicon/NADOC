import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initZoomVolume } from './zoom_volume.js'

let panel
const listeners = new Set(), frames = new Set()
function setup(assembly = false, saved = []) {
  document.body.innerHTML = '<div id="right-tab-content-visualization"></div>'
  let state = { currentDesign: { id: 'part', zoom_volumes: saved }, assemblyActive: assembly, currentAssembly: { id: 'assembly' }, selection: { items: [{ kind: 'strand', id: 's1' }] }, activeInstanceId: 'i1' }
  const update = patch => { const previous = state; state = { ...state, ...patch }; for (const cb of [...listeners]) cb(state, previous) }
  const store = { setState: update, getState: () => state, subscribe: cb => { listeners.add(cb); return () => listeners.delete(cb) } }
  panel = initZoomVolume({ document, scene: new THREE.Scene(), canvas: document.createElement('canvas'), store,
    designRenderer: {}, assemblyRenderer: {}, addFrameCallback: cb => frames.add(cb), removeFrameCallback: cb => frames.delete(cb) })
  update.state = () => state
  return update
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


it('restores stable volume identities, magnification and settings after document reload and presentation selection', () => {
  const value = { id: 'saved-zoom', name: 'Saved detail', zoom_step: 3, targets: [{ refs: [{ kind: 'strand', id: 's' }] }],
    settings: { enabled: false, representation: 'beads', coloring: 'base', position: 'bl' } }
  const update = setup(false, [value])
  expect(panel.list()).toEqual([{ id: 'saved-zoom', name: 'Saved detail', visible: false }])
  expect(panel.debug().entries[0].zoom).toBe(1.25 ** 3)
  window.dispatchEvent(new CustomEvent('nadoc:presentation-frame', { detail: { documentId: 'part', zoomVolumeIds: ['saved-zoom'] } }))
  expect(panel.debug().entries[0].zoom).toBe(1.25 ** 3)
  window.dispatchEvent(new CustomEvent('nadoc:presentation-frame', { detail: null }))
  expect(panel.list()[0].visible).toBe(false)
  update({ currentDesign: { id: 'other' } })
  update({ currentDesign: { id: 'part', zoom_volumes: [value] } })
  expect(panel.debug().entries[0].zoom).toBe(1.25 ** 3)
  expect(document.querySelector('[data-control="coloring"]').value).toBe('base')
})


it('saves the adjusted lens in the document immediately and retains it when selections change', () => {
  const update = setup(); const id = panel.capture()
  document.querySelector('.zoom-volume-zoom-controls button').click()
  expect(update.state().currentDesign.zoom_volumes[0]).toMatchObject({ id, zoom_step: 1 })
  update({ selection: { items: [{ kind: 'strand', id: 'replacement' }] } })
  document.querySelector('[data-control="set"]').click()
  expect(update.state().currentDesign.zoom_volumes[0]).toMatchObject({ id, zoom_step: 1, targets: [{ refs: [{ id: 'replacement' }] }] })
  document.querySelector('[data-control="delete"]').click()
  expect(update.state().currentDesign.zoom_volumes).toEqual([])
})


it('keeps an inset through a stale document response while its magnification saves', async () => {
  const update = setup(); panel.capture()
  document.querySelector('.zoom-volume-zoom-controls button').click()
  update({ currentDesign: { ...update.state().currentDesign, zoom_volumes: [] } })
  expect(panel.debug().entries[0].zoom).toBe(1.25)
  await Promise.resolve(); await Promise.resolve()
  expect(update.state().currentDesign.zoom_volumes[0].zoom_step).toBe(1)
})

it('persists and restores an arbitrary mixed base selection without widening its refs', () => {
  const update = setup()
  const refs = ['h:3:REVERSE:1', '__ext_tail:0:FORWARD', '__xb__:xo:2'].map(key => ({ kind: 'base', key }))
  update({ selection: { items: refs } })
  panel.capture()
  const saved = update.state().currentDesign.zoom_volumes
  expect(saved[0].targets).toEqual([{ refs }])
  panel.dispose(); panel = null
  setup(false, saved)
  expect(panel.debug().entries[0].targets).toEqual([{ refs }])
})

it('persists independent inset titles and annotation font presets, including legacy defaults', () => {
  const update = setup(); panel.capture(); panel.capture()
  const rows = document.querySelectorAll('.zoom-volume-row')
  const control = key => rows[0].querySelector(`[data-control="${key}"]`)
  const change = (key, value) => { control(key).value = value; control(key).dispatchEvent(new Event('change', { bubbles: true })) }
  expect([...control('title-size').options].map(o => o.value)).toEqual(['10', '11', '12', '13', '14', '16', '18', '20', '24', '28', '32', '48', '64', '96'])
  expect([...control('title-font').options].map(o => o.value)).toEqual(['system-ui', 'Arial', 'Verdana', 'Georgia', 'Times New Roman', 'monospace'])
  change('name', 'Crossover detail'); change('title-size', '48'); change('title-font', 'Georgia')
  const titles = document.querySelectorAll('.zoom-volume-title')
  expect(titles[0].textContent).toBe('Crossover detail')
  expect(titles[0].style.fontSize).toBe('48px')
  expect(titles[0].style.fontFamily).toBe('Georgia')
  expect(titles[0].parentElement.style.getPropertyValue('--zoom-title-height')).toBe('68px')
  expect(titles[1].style.fontSize).toBe('12px')
  const saved = structuredClone(update.state().currentDesign.zoom_volumes)
  panel.dispose(); panel = null
  delete saved[1].settings['title-size']; delete saved[1].settings['title-font']
  setup(false, saved)
  const restored = document.querySelectorAll('.zoom-volume-title')
  expect(restored[0].textContent).toBe('Crossover detail')
  expect(restored[0].style.fontFamily).toBe('Georgia')
  expect(restored[0].style.fontSize).toBe('48px')
  expect(restored[1].style.fontSize).toBe('12px')
  expect(restored[1].style.fontFamily).toBe('system-ui')
})
it('restores legacy square sizes and persists independent rectangular sizes and highlights',()=>{
 const update=setup(false,[{id:'saved',name:'Saved',targets:[{refs:[{kind:'strand',id:'s1'}]}],settings:{size:350,highlight:true}}])
 const row=document.querySelector('.zoom-volume-row')
 expect(row.querySelector('[data-control=size]')).toBeNull()
 expect(document.querySelectorAll('[data-resize-edge]')).toHaveLength(8)
 expect(row.querySelector('[data-control=highlight]').checked).toBe(true)
 row.querySelector('[data-control=highlight]').click()
 const saved=update.state().currentDesign.zoom_volumes[0]
 expect(saved.settings).toMatchObject({width:350,height:350,highlight:false})
 expect(update.state().selection.items).toEqual([{kind:'strand',id:'s1'}])
})
