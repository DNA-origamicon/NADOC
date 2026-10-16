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
import { showToast } from './toast.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))

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

describe('cluster panel — dissolve group', () => {
  let store, api, panel, visibility
  const button = () => rows()[0].querySelector('button[aria-label="Dissolve group"]')
  beforeEach(() => {
    localStorage.clear(); vi.clearAllMocks(); mountDom()
    store = createMockStore({ currentDesign: design(), selection: { items: [] }, lastError: { message: 'Group still owns a lattice frame' } })
    api = { patchCluster: vi.fn(), createCluster: vi.fn(), deleteCluster: vi.fn() }
    visibility = vi.fn(ids => new Set(ids))
    panel = initClusterPanel(store, { api, onClusterClick: vi.fn(), onVisibilityChange: visibility })
    store.setState({ currentDesign: design() })
    rows()[0].querySelector('button[title="Hide cluster"]').click()
  })
  afterEach(() => { panel?.destroy(); document.body.innerHTML = ''; localStorage.clear(); vi.restoreAllMocks() })

  it('names the operation and explains that members are kept', () => {
    expect(button()).not.toBeNull()
    expect(button().title).toMatch(/keep members/i)
  })

  it.each(['null', 'throw'])('keeps a hidden group hidden while pending and after %s refusal', async failure => {
    let resolve, reject
    api.deleteCluster.mockImplementation(() => new Promise((done, fail) => { resolve = done; reject = fail }))
    button().click()
    expect(api.deleteCluster).toHaveBeenCalledExactlyOnceWith('cA')
    store.setState({ currentDesign: design() })
    expect(rows()[0].querySelector('button[title="Show cluster"]')).not.toBeNull()
    if (failure === 'throw') reject(new Error('Dissolve disconnected'))
    else resolve(null)
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining(failure === 'throw' ? 'Dissolve disconnected' : 'Group still owns a lattice frame'), { severity: 'error' }))
    store.setState({ currentDesign: design() })
    expect(rows()[0].querySelector('button[title="Show cluster"]')).not.toBeNull()
    expect(visibility).toHaveBeenCalledTimes(1)
  })

  it('removes the visibility override only after an accepted dissolve', async () => {
    let resolve
    api.deleteCluster.mockImplementation(() => new Promise(done => { resolve = done }))
    button().click(); expect(visibility).toHaveBeenCalledTimes(1)
    const remaining = { ...design(), cluster_transforms: [design().cluster_transforms[1]] }
    store.setState({ currentDesign: remaining }); resolve({ design: remaining })
    await vi.waitFor(() => expect(visibility).toHaveBeenCalledTimes(2))
    expect(visibility.mock.results.at(-1).value).toEqual(new Set())
    expect(rows()).toHaveLength(1); expect(rows()[0].dataset.clusterId).toBe('cB')
  })

  it('does not prune visibility when a non-null stale response leaves the current group present', async () => {
    let resolve
    api.deleteCluster.mockImplementation(() => new Promise(done => { resolve = done }))
    button().click()
    const remaining = { ...design(), cluster_transforms: [design().cluster_transforms[1]] }
    resolve({ design: remaining }); await Promise.resolve(); await Promise.resolve()
    store.setState({ currentDesign: design() })
    expect(rows()[0].querySelector('button[title="Show cluster"]')).not.toBeNull()
    expect(visibility).toHaveBeenCalledTimes(1)
  })
})

describe('cluster panel — style round trip', () => {
  let store, api, panel, onStylePreview

  beforeEach(() => {
    vi.useFakeTimers()
    mountDom()
    store = createMockStore({ currentDesign: design(), selection: { items: [] } })
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

  it('marks rows from canonical cluster selection', () => {
    store.setState({ selection: { items: [{ kind: 'cluster', id: 'cB' }] } })
    expect(document.querySelector('[data-cluster-id="cA"]').getAttribute('aria-selected')).toBe('false')
    expect(document.querySelector('[data-cluster-id="cB"]').getAttribute('aria-selected')).toBe('true')
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

  it('THE REPORTED BUG: colour-map pick + click outside updates the sidebar pill', () => {
    // A native colour input fires `input` live while its map is open and `change` only
    // when the map is dismissed — so this flow produced previews (3D updated) and no
    // commit (store, and therefore the pill, did not).
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('input', { bubbles: true }))
    vi.advanceTimersByTime(20)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    vi.advanceTimersByTime(300)

    expect(api.patchCluster).toHaveBeenCalledWith('cA', { color: '#ff0000' })
    expect(store.getState().currentDesign.cluster_transforms[0].color).toBe('#ff0000')
    expect(swatchBg(rows()[0])).toBe('#ff0000')
  })

  it('…and the colour then SURVIVES a later opacity edit', () => {
    // The earlier "reverts to an old colour" symptom was this same uncommitted colour
    // being wiped by the next repaint from the store.
    swatchOf(rows()[0]).click()
    colorInput().value = '#ff0000'
    colorInput().dispatchEvent(new Event('input', { bubbles: true }))
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    vi.advanceTimersByTime(300)

    swatchOf(rows()[0]).click()
    rangeInput().value = '0.4'
    rangeInput().dispatchEvent(new Event('change', { bubbles: true }))
    vi.advanceTimersByTime(300)

    const c = store.getState().currentDesign.cluster_transforms[0]
    expect(c.color).toBe('#ff0000')
    expect(c.opacity).toBeCloseTo(0.4)
    expect(swatchBg(rows()[0])).toBe('#ff0000')
  })
})

it('repairs unassigned components once and disables repair in assemblies', async () => {
  mountDom()
  const button = document.createElement('button')
  button.id = 'cluster-repair-btn'; document.body.append(button)
  const store = createMockStore({ currentDesign: design(), selection: { items: [] } })
  let finish
  const api = { clusterUnassignedComponents: vi.fn(() => new Promise(resolve => { finish = resolve })) }
  initClusterPanel(store, { onClusterClick: () => {}, api })
  button.click(); button.click()
  expect(api.clusterUnassignedComponents).toHaveBeenCalledOnce()
  expect(button.disabled).toBe(true)
  finish(); await Promise.resolve(); await Promise.resolve()
  expect(button.disabled).toBe(false)
  store.setState({ assemblyActive: true })
  expect(button.disabled).toBe(true)
  document.body.innerHTML = ''
})

describe('cluster panel assembly display loading', () => {
  beforeEach(() => { mountDom(); localStorage.removeItem('nadoc.leftSidebar.sections.v1') })
  afterEach(() => { document.body.innerHTML = ''; localStorage.removeItem('nadoc.leftSidebar.sections.v1') })

  it('uses the ready renderer Design for a hidden panel and refreshes when expanded', async () => {
    let finish, rendered = null
    const waitForAssemblyReady = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const api = { getInstanceDesign: vi.fn() }
    const instance = { id: 'part', name: 'Part', source: { type: 'file', path: '/part' }, geometrySourceKey: 'f:/part:100:' }
    const assembly = { instances: [instance] }
    const store = createMockStore({ assemblyActive: true, currentAssembly: assembly })
    const panel = initClusterPanel(store, { api, getInstanceDesign: () => rendered, waitForAssemblyReady })
    document.getElementById('cluster-panel-heading').click()
    panel.setAssemblyMode(assembly)
    panel.expandInstance('part')
    expect(api.getInstanceDesign).not.toHaveBeenCalled()
    rendered = design()
    finish()
    // Both hidden-panel state and later expansion must use the loaded Design.
    await vi.waitFor(() => expect(waitForAssemblyReady).toHaveBeenCalledOnce())
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    document.getElementById('cluster-panel-heading').click()
    expect(document.getElementById('cluster-list').textContent).toContain('Cluster A')
    expect(api.getInstanceDesign).not.toHaveBeenCalled()
    panel.clearAssemblyMode()
    panel.destroy()
  })

  it('does not populate a newer same-ID assembly from a stale wait', async () => {
    const waits = []
    const waitForAssemblyReady = (assembly, options) => new Promise(resolve => waits.push({ assembly, ...options, resolve }))
    let rendered = null
    const api = { getInstanceDesign: vi.fn() }
    const source = { type: 'file', path: '/part' }
    const old = { instances: [{ id: 'part', name: 'Old', source, geometrySourceKey: 'f:/part:100:' }] }
    const fresh = { instances: [{ id: 'part', name: 'New', source, geometrySourceKey: 'f:/part:101:' }] }
    const panel = initClusterPanel(createMockStore({ assemblyActive: true }), { api, getInstanceDesign: () => rendered, waitForAssemblyReady })
    panel.setAssemblyMode(old)
    panel.setAssemblyMode(fresh)
    expect(waits[0].signal.aborted).toBe(true)
    waits[0].resolve()
    await Promise.resolve(); await Promise.resolve()
    expect(api.getInstanceDesign).not.toHaveBeenCalled()
    rendered = { cluster_transforms: [{ id: 'new', name: 'Fresh cluster', helix_ids: [] }] }
    waits[1].resolve()
    panel.expandInstance('part')
    await vi.waitFor(() => expect(document.getElementById('cluster-list').textContent).toContain('Fresh cluster'))
    expect(document.getElementById('cluster-list').textContent).not.toContain('Old')
    expect(api.getInstanceDesign).not.toHaveBeenCalled()
    panel.clearAssemblyMode()
    panel.destroy()
  })
})
