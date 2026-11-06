import { afterEach, describe, expect, it } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initEditorViewTools, nextViewTools } from './view_tools.js'
let view
const d = (start, end, direction) => ({ helix_id: 'h', start_bp: start, end_bp: end, direction })
const design = { helices: [{ id: 'h' }], strands: [
  { id: 'sc', strand_type: 'scaffold', domains: [d(0, 31, 'FORWARD')] },
  { id: 's', strand_type: 'staple', domains: [d(15, 0, 'REVERSE'), d(31, 16, 'REVERSE')], sequence: 'ACGT'.repeat(8) },
] }
function setup() {
  document.body.innerHTML = '<div id="view-tools">' + ['lengthHeatmap', 'stapleTemperature', 'grid'].map(k => `<button class="vt-btn" data-vt="${k}"><span class="sf-label-text"></span></button>`).join('') + '</div><div id="pathview-container"></div>'
  const store = createMockStore({ design, viewTools: { lengthHeatmap: false, stapleTemperature: 'off', grid: true } })
  view = initEditorViewTools({ store })
  return { store, click: k => document.querySelector(`[data-vt="${k}"]`).click() }
}
afterEach(() => { view?.dispose(); view = null; document.body.innerHTML = '' })
describe('cadnano view tools', () => {
  it('cycles the temperature mode and makes it exclusive with length', () => {
    let state = { lengthHeatmap: true, grid: true }
    state = nextViewTools(state, 'stapleTemperature')
    expect(state).toMatchObject({ lengthHeatmap: false, stapleTemperature: 'domain', grid: true })
    state = nextViewTools(state, 'stapleTemperature'); expect(state.stapleTemperature).toBe('total')
    state = nextViewTools(state, 'stapleTemperature'); expect(state.stapleTemperature).toBe('off')
    expect(nextViewTools({ ...state, stapleTemperature: 'total' }, 'lengthHeatmap')).toMatchObject({ lengthHeatmap: true, stapleTemperature: 'off' })
  })
  it('shows the shared scientific legend, mode label and ordinary toggle states', () => {
    const f = setup(), legend = document.getElementById('staple-temperature-legend')
    expect(legend.hidden).toBe(true)
    f.click('stapleTemperature')
    expect(legend.hidden).toBe(false)
    expect(legend.textContent).toContain('10 mM MgCl₂')
    expect(legend.querySelector('[data-temperature-title]').textContent).toBe('Domain Tm (°C)')
    expect(document.querySelector('[data-vt="stapleTemperature"]').dataset.mode).toBe('domain')
    f.click('stapleTemperature')
    expect(legend.querySelector('[data-temperature-title]').textContent).toBe('Total staple Tfold (°C)')
    f.click('lengthHeatmap'); expect(legend.hidden).toBe(true)
    f.click('grid'); expect(f.store.getState().viewTools.grid).toBe(false)
  })
  it('updates estimates after a sequence edit and clears the legend after unload', () => {
    const f = setup(); f.click('stapleTemperature')
    expect(document.querySelector('[data-temperature-status]').textContent).toContain('0 gray')
    f.store.setState({ design: { ...design, strands: design.strands.map(s => ({ ...s, sequence: null })) } })
    expect(document.querySelector('[data-temperature-status]').textContent).toContain('2 gray')
    f.store.setState({ design: null })
    expect(document.querySelector('[data-temperature-status]').textContent).toBe('Open a sequenced part.')
  })
  it('removes its listener and legend on disposal', () => {
    const f = setup(); view.dispose(); view = null; f.click('stapleTemperature')
    expect(f.store.getState().viewTools.stapleTemperature).toBe('off')
    expect(document.getElementById('staple-temperature-legend')).toBeNull()
  })
})

it('stores temperature bounds in view state and retains them when cycling modes', () => {
  const f = setup(); f.click('stapleTemperature')
  const low = document.querySelector('[data-temperature-low]')
  low.value = '45'; low.dispatchEvent(new Event('change'))
  expect(f.store.getState().viewTools.temperatureBounds).toEqual({ lo: 45, hi: 90 })
  f.click('stapleTemperature'); expect(low.value).toBe('45')
  expect(f.store.getState().design).toBe(design)
})
