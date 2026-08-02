// @vitest-environment jsdom
/**
 * cluster_panel.test.js — the sidebar's cluster-style round trip.
 *
 * Written to chase two reported symptoms: after changing a cluster's colour and then its
 * opacity the colour reverted to an older one, and colours that were correct in 3D were
 * not reflected in the row swatch or the popover's colour input.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initClusterPanel } from './cluster_panel.js'
import { withClusterDisplay } from '../scene/cluster_entries.js'

function mountDom() {
  document.body.innerHTML = `
    <div id="cluster-panel">
      <div id="cluster-panel-heading"><span id="cluster-panel-arrow"></span></div>
      <div id="cluster-panel-body"><div id="cluster-list"></div></div>
    </div>
    <button id="cluster-new-btn"></button>`
}

const design = (over = {}) => ({
  strands: [], extensions: [],
  cluster_transforms: [
    { id: 'cA', name: 'Cluster A', helix_ids: ['h1'], ...over.a },
    { id: 'cB', name: 'Cluster B', helix_ids: ['h2'], ...over.b },
  ],
})

const rows = () => [...document.querySelectorAll('#cluster-list > div')]
/** The swatch is identified by its title; jsdom rewrites inline colours to rgb(). */
const swatchOf = (row) => [...row.querySelectorAll('button')]
  .find(b => (b.title ?? '').startsWith('Colour'))
// Read the raw style attribute: jsdom's cssstyle does not expand the `background`
// shorthand into backgroundColor, so `.style.backgroundColor` is always ''.
// jsdom's cssstyle refuses the panel's full cssText string, so the swatch colour is set
// as its own property — which is also what makes it readable here at all.
const hexOf = (v) => {
  const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(v ?? '')
  return m ? '#' + [1, 2, 3].map(i => Number(m[i]).toString(16).padStart(2, '0')).join('')
           : (v ?? '').toLowerCase()
}
const swatchBg = (row) => hexOf(swatchOf(row).style.backgroundColor)
const colorInput = () => document.querySelector('.cluster-style-popover input[type=color]')
const rangeInput = () => document.querySelector('.cluster-style-popover input[type=range]')

describe('cluster panel — style round trip', () => {
  let store, api, panel, onStylePreview

  beforeEach(() => {
    vi.useFakeTimers()
    mountDom()
    store = createMockStore({ currentDesign: design(), multiSelectedClusterIds: [] })
    onStylePreview = vi.fn()
    api = {
      patchCluster: vi.fn(async (id, body) => {
        // Mirror the real client: the response design is written back to the store.
        const d = store.getState().currentDesign
        store.setState({
          currentDesign: {
            ...d,
            cluster_transforms: d.cluster_transforms.map(c => c.id === id ? { ...c, ...body } : c),
          },
        })
      }),
      createCluster: vi.fn(), deleteCluster: vi.fn(),
    }
    panel = initClusterPanel(store, { onClusterClick: () => {}, api, onStylePreview })
    // Force the initial render.
    store.setState({ currentDesign: design() })
  })

  afterEach(() => { panel?.destroy?.(); vi.useRealTimers(); document.body.innerHTML = '' })

  it('renders a swatch per cluster', () => {
    expect(rows()).toHaveLength(2)
    expect(swatchOf(rows()[0])).toBeTruthy()
  })

  it('an unstyled cluster shows its auto palette slot', () => {
    expect(swatchBg(rows()[0])).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('commits a colour change through the API', () => {
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)
    expect(api.patchCluster).toHaveBeenCalledWith('cA', { color: '#ff0000' })
  })

  it('THE ROW SWATCH reflects the committed colour', () => {
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)
    expect(swatchBg(rows()[0])).toBe('#ff0000')
  })

  it('THE POPOVER shows the committed colour when reopened', () => {
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)
    // Reopen from the freshly rebuilt row.
    swatchOf(rows()[0]).click()
    expect(colorInput().value.toLowerCase()).toBe('#ff0000')
  })

  it('changing OPACITY after a colour does not revert the colour', () => {
    // The reported bug, end to end.
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)

    // The popover is still open across the rebuild — the user just drags the slider.
    rangeInput().value = '0.4'
    rangeInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)

    const c = store.getState().currentDesign.cluster_transforms.find(x => x.id === 'cA')
    expect(c.color).toBe('#ff0000')
    expect(c.opacity).toBeCloseTo(0.4)
    expect(swatchBg(rows()[0])).toBe('#ff0000')
  })

  it('the opacity PREVIEW carries the already-committed colour', () => {
    // If the preview design were stale, 3D would repaint the OLD colour mid-drag.
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)

    rangeInput().value = '0.4'
    rangeInput().dispatchEvent(new Event('input', { bubbles: true }))
    vi.advanceTimersByTime(50)
    expect(onStylePreview).toHaveBeenCalled()
    const [, patch] = onStylePreview.mock.calls.at(-1)
    expect(patch.color).toBeUndefined()          // opacity-only patch
    const live = store.getState().currentDesign.cluster_transforms.find(x => x.id === 'cA')
    expect(live.color).toBe('#ff0000')           // …and the design it patches is current
  })

  it('THE REPORTED BUG: an opacity drag while the colour PATCH is still in flight', () => {
    // The commit is debounced, so `currentDesign` can lag the colour the user just
    // picked. A preview built only from the store would repaint the OLD colour — which
    // is what "change the colour, change the opacity, it reverts" was.
    let release
    api.patchCluster = vi.fn(() => new Promise((res) => { release = res }))

    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)                 // commit fired, response NOT back

    rangeInput().value = '0.4'
    rangeInput().dispatchEvent(new Event('input', { bubbles: true }))
    vi.advanceTimersByTime(50)

    const [, patch, uiState] = onStylePreview.mock.calls.at(-1)
    expect(patch).toEqual({ opacity: 0.4 })     // only the opacity half repaints

    // The store has NOT caught up — this is the state main.js would have built from.
    const stale = store.getState().currentDesign.cluster_transforms.find(c => c.id === 'cA')
    expect(stale.color).toBeUndefined()

    // …and this is what main.js actually builds: store design + the popover's full UI
    // state. It must carry the in-flight colour, or 3D repaints the old one.
    const preview = withClusterDisplay(store.getState().currentDesign, 'cA', uiState)
    expect(preview.cluster_transforms.find(c => c.id === 'cA').color).toBe('#ff0000')
    release?.()
  })

  it('the preview state survives a rebuild that lands mid-interaction', () => {
    swatchOf(rows()[0]).click()
    colorInput().value = '#00ff00'
    colorInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)                 // commit lands → list rebuilds

    rangeInput().value = '0.6'
    rangeInput().dispatchEvent(new Event('input', { bubbles: true }))
    vi.advanceTimersByTime(50)
    const [, , uiState] = onStylePreview.mock.calls.at(-1)
    expect(uiState.color).toBe('#00ff00')
  })
})
