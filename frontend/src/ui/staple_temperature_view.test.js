import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initStapleTemperatureView, temperatureColor, UNKNOWN_TEMPERATURE_COLOR } from './staple_temperature_view.js'
import { initViewToolButtons } from './view_tool_buttons.js'
const dom = (start, end, direction) => ({ helix_id: 'h', start_bp: start, end_bp: end, direction })
const design = { helices: [{ id: 'h' }], strands: [
  { id: 'sc', strand_type: 'scaffold', domains: [dom(0, 31, 'FORWARD')] },
  { id: 's', strand_type: 'staple', sequence: 'ACGT'.repeat(8), domains: [dom(15, 0, 'REVERSE'), dom(31, 16, 'REVERSE')] },
] }
let api, mesh
function fixture() {
  document.body.innerHTML = '<button class="vt-btn" data-vt="stapleTemperature"><span class="sf-label-text"></span></button><button class="vt-btn" data-vt="lengthHeatmap"></button><div id="length-heatmap-legend"></div><div id="staple-temperature-legend" hidden><strong data-temperature-title></strong><span data-temperature-status></span></div>'
  const store = createMockStore({ currentDesign: design })
  mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial(), 2)
  mesh.setColorAt(0, new THREE.Color(0x123456)); mesh.setColorAt(1, new THREE.Color(0xabcdef))
  let entries = [0, 1].map(i => ({ id: i, instMesh: mesh, defaultColor: 0xffffff, nuc: { strand_id: 's', domain_index: i } }))
  const renderer = { getBackboneEntries: () => entries, setEntryColor: (e, c) => e.instMesh.setColorAt(e.id, new THREE.Color(c)) }
  const button = document.querySelector('[data-vt="stapleTemperature"]')
  const color = i => { const c = new THREE.Color(); mesh.getColorAt(i, c); return c.getHex() }
  return { store, renderer, button, color, replaceEntries: () => { entries = entries.map(e => ({ ...e })) } }
}
afterEach(() => { api?.dispose(); api = null; mesh?.geometry.dispose(); mesh?.material.dispose(); mesh?.dispose(); document.body.innerHTML = '' })
describe('temperature overlay', () => {
  it('maps a fixed Celsius scale and keeps missing estimates distinct', () => {
    expect(temperatureColor(20)).toBe(0x0d0df2)
    expect(temperatureColor(90)).toBe(0xf20d0d)
    expect(temperatureColor(null)).toBe(UNKNOWN_TEMPERATURE_COLOR)
    expect(temperatureColor(NaN)).toBe(UNKNOWN_TEMPERATURE_COLOR)
  })
  it('cycles off/domain/total/off and restores actual prior colors', () => {
    const f = fixture(); api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer })
    expect(document.getElementById('staple-temperature-legend').hidden).toBe(true)
    f.button.click(); expect(api.getMode()).toBe('domain')
    expect(f.button.getAttribute('aria-pressed')).toBe('true')
    expect(f.color(0)).not.toBe(0x123456)
    expect(document.querySelector('[data-temperature-status]').textContent).toContain('0 gray')
    f.button.click(); expect(api.getMode()).toBe('total')
    expect(document.querySelector('[data-temperature-title]').textContent).toContain('Tfold')
    f.button.click(); expect(f.color(0)).toBe(0x123456); expect(f.color(1)).toBe(0xabcdef)
    expect(document.getElementById('staple-temperature-legend').hidden).toBe(true)
  })
  it('invalidates sequence estimates and paints unknown gray on an edit', () => {
    const f = fixture(); api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer })
    f.button.click()
    f.store.setState({ currentDesign: { ...design, strands: design.strands.map(s => ({ ...s, sequence: null })) } })
    expect(f.color(0)).toBe(UNKNOWN_TEMPERATURE_COLOR)
    expect(document.querySelector('[data-temperature-status]').textContent).toContain('2 gray')
  })
  it('reapplies to fresh entries after a display rebuild', () => {
    const f = fixture(); api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer })
    f.button.click(); f.replaceEntries(); mesh.setColorAt(0, new THREE.Color(0xaabbcc))
    window.dispatchEvent(new Event('nadoc:display-rebuilt'))
    expect(f.color(0)).not.toBe(0xaabbcc)
    api.setMode('off'); expect(f.color(0)).toBe(0xaabbcc)
  })
  it('explains unavailable representations and resumes on return', () => {
    const f = fixture(); let repr = 'full'
    api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer, getCurrentRepr: () => repr })
    f.button.click(); repr = 'vdw'; window.dispatchEvent(new Event('nadoc:representation-change'))
    expect(f.color(0)).toBe(0x123456)
    expect(document.querySelector('[data-temperature-status]').textContent).toContain('Full or Beads')
    repr = 'beads'; window.dispatchEvent(new Event('nadoc:representation-change'))
    expect(f.color(0)).not.toBe(0x123456)
  })
  it('makes length and temperature modes mutually exclusive', () => {
    const f = fixture()
    const view = initViewToolButtons({ store: f.store, designRenderer: f.renderer, scene: { add: vi.fn() },
      expandedSpacing: { isActive: () => false }, getUndefinedHighlightOn: () => false })
    api = view.temperatureView
    const length = document.querySelector('[data-vt="lengthHeatmap"]')
    length.click(); expect(view.isLengthHeatmapOn()).toBe(true)
    f.button.click(); expect(view.isLengthHeatmapOn()).toBe(false); expect(api.getMode()).toBe('domain')
    length.click(); expect(api.getMode()).toBe('off'); expect(view.isLengthHeatmapOn()).toBe(true)
  })
  it('tears down listeners and restores colors', () => {
    const f = fixture(); api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer })
    f.button.click(); api.dispose(); api = null; f.button.click(); expect(f.color(0)).toBe(0x123456)
  })
})

it('recolors the 3D entries for edited bounds and retains them across mode changes', () => {
  const f = fixture(); api = initStapleTemperatureView({ store: f.store, designRenderer: f.renderer })
  f.button.click()
  const before = f.color(0), low = document.querySelector('[data-temperature-low]')
  low.value = '80'; low.dispatchEvent(new Event('change'))
  expect(f.color(0)).not.toBe(before)
  f.button.click(); expect(low.value).toBe('80')
  api.setMode('off'); expect(f.color(0)).toBe(0x123456)
  api.setMode('domain'); expect(low.value).toBe('80')
})
