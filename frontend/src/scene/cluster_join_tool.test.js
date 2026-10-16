import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initClusterJoinTool, nearbyJoinSites } from './cluster_join_tool.js'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const port = (id, cluster, position, kind = 'side') => ({ id, cluster_id: cluster, kind, position, normal: [0, 1, 0], axis: [1, 0, 0], from: { helix_id: cluster.toLowerCase(), bp_index: 12, direction: 'FORWARD' }, to: { helix_id: cluster.toLowerCase(), bp_index: 13, direction: 'FORWARD' } })
const a = port('a-side', 'A', [-8, 0, 0]), a2 = port('a-end', 'A', [-8, 5, 0], 'end'), b = port('b-end', 'B', [8, 0, 0], 'end')
const catalog = () => ({ design_id: 'part', revision: 7, clusters: [
  { cluster_id: 'A', name: 'Body', eligible: true, helix_ids: ['a'], ports: [a, a2] },
  { cluster_id: 'B', name: 'Branch', eligible: true, helix_ids: ['b'], ports: [b] },
], sites: [a, a2, b] })
const validPreview = (overrides = {}) => ({ valid: true, errors: [], warnings: [], preview_token: 'token-1', design_id: 'part', revision: 7,
  donor_helix_ids: ['b'], donor_world_delta: new THREE.Matrix4().makeTranslation(-16, 1, 0).toArray(),
  bridges: [{ from: [-8, 0, 0], to: [-8, 1, 0], points: [[-8, 0, 0], [-8, 0.5, 0.4], [-8, 1, 0]], span_nm: 1, extra_bases: 3 }, { from: [-7, 1, 0], to: [-7, 0, 0], points: [[-7, 1, 0], [-7, 0, 0]], span_nm: 1, extra_bases: 3 }], scaffold_count_before: 2, scaffold_count_after: 1, ...overrides })
let tool
function setup(extra = {}) {
  vi.useFakeTimers()
  document.body.innerHTML = '<canvas id="canvas"></canvas>'
  const canvas = document.getElementById('canvas')
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600 })
  canvas.setPointerCapture = vi.fn(); canvas.hasPointerCapture = vi.fn(() => false)
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 4 / 3, 0.1, 500)
  camera.position.set(0, 0, 80); camera.lookAt(0, 0, 0); camera.updateMatrixWorld()
  const design = { id: 'part', helices: [{ id: 'a' }, { id: 'b' }], cluster_transforms: [{ id: 'A', helix_ids: ['a'] }, { id: 'B', helix_ids: ['b'] }] }
  const store = createMockStore({ currentDesign: design, joinActive: false, selection: { items: [{ kind: 'cluster', id: 'A' }] }, currentHelixAxes: { a: { start: [-8, 0, 0], end: [-8, 5, 0] }, b: { start: [8, 0, 0], end: [8, 5, 0] } } })
  let revision = 7, documentToken = 'doc-A'
  const api = { getClusterJoinSites: vi.fn(async () => catalog()), previewClusterJoin: vi.fn(async () => validPreview()), applyClusterJoin: vi.fn(async () => ({ design: { ...design }, revision: 8 })), currentRevisionWatermark: () => revision }
  const onApplied = vi.fn(async response => { store.setState({ currentDesign: response.design }); return true })
  tool = initClusterJoinTool({ store, scene, canvas, camera, api, onApplied, getDocumentToken: () => documentToken, ...extra })
  return { tool, store, api, scene, canvas, camera, onApplied, design, setRevision: value => { revision = value }, setDocumentToken: value => { documentToken = value } }
}
async function choosePair() { tool.testApi.pickSite('a-side'); tool.testApi.pickSite('b-end'); await vi.advanceTimersByTimeAsync(130) }
afterEach(() => { tool?.dispose(); tool = null; vi.useRealTimers(); document.body.innerHTML = '' })

describe('native Join controller', () => {
  it('uses native ports, fixes the first cluster, previews the entire moving pose and commits exactly once', async () => {
    const { api, store, scene, onApplied, design } = setup()
    await tool.activate()
    expect(store.getState().joinActive).toBe(true)
    tool.testApi.pickSite('a-side')
    expect(tool.testApi.pickSite('a-end')).toBe(false)
    expect(tool.getState().first.id).toBe('a-side')
    tool.testApi.pickSite('b-end')
    await vi.advanceTimersByTimeAsync(130)
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
    expect(api.previewClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ first: { cluster_id: 'A', port_id: 'a-side' }, second: { cluster_id: 'B', port_id: 'b-end' }, expected_design_id: 'part', expected_revision: 7 }), expect.anything())
    const ghost = scene.getObjectByName('cluster-join-ghost')
    ghost.updateMatrixWorld(true)
    expect(ghost.children).toHaveLength(1)
    expect(new THREE.Box3().setFromObject(ghost).getCenter(new THREE.Vector3()).x).toBeCloseTo(-8)
    const anchors = scene.getObjectByName('cluster-join-markers').children.filter(mesh => ['fixed', 'moving'].includes(mesh.userData.role))
    expect(anchors).toHaveLength(2)
    expect(anchors.every(mesh => mesh.material.wireframe)).toBe(true)
    expect(store.getState().currentDesign).toBe(design)
    const one = tool.apply(), duplicate = tool.apply()
    await Promise.all([one, duplicate])
    expect(api.applyClusterJoin).toHaveBeenCalledOnce()
    expect(api.applyClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ preview_token: 'token-1', expected_revision: 7 }))
    expect(onApplied).toHaveBeenCalledOnce()
    expect(tool.isActive()).toBe(false)
    expect(scene.getObjectByName('cluster-join-ghost').children).toHaveLength(0)
  })

  it('preserves native design and the chosen points on backend failure', async () => {
    const { api, store, design } = setup()
    const originalSelection = store.getState().selection
    await tool.activate(); await choosePair()
    api.applyClusterJoin.mockImplementation(async () => { store.setState({ lastError: { status: 422, message: 'Scaffold continuity would be broken' } }); return null })
    expect(await tool.apply()).toBe(false)
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.getState().second.id).toBe('b-end')
    expect(store.getState().currentDesign).toBe(design)
    expect(store.getState().selection).toBe(originalSelection)
    expect(document.querySelector('[data-join-status]').textContent).toContain('continuity')
    expect(tool.isActive()).toBe(true)
    expect(tool.getState().needsResync).toBe(false)
    expect(tool.getState().preview.valid).toBe(true)
  })

  it('requires a design refresh after an ambiguous transport failure without replaying the mutation', async () => {
    const { api, store, design } = setup()
    await tool.activate(); await choosePair()
    api.applyClusterJoin.mockRejectedValue(new TypeError('Failed to fetch'))
    await tool.apply()
    expect(tool.getState().needsResync).toBe(true)
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.getState().preview).toBe(null)
    expect(store.getState().currentDesign).toBe(design)
    expect(document.querySelector('[data-join-refresh]').textContent).toBe('Refresh design')
    tool.updateParameters({ gap_nm: 1.2 }); await vi.advanceTimersByTimeAsync(130)
    expect(api.previewClusterJoin).toHaveBeenCalledOnce()
    expect(await tool.apply()).toBe(false)
    expect(api.applyClusterJoin).toHaveBeenCalledOnce()
    api.getDesign = vi.fn(async () => { const response = { design: { ...design }, revision: 8 }; store.setState({ currentDesign: response.design }); return response })
    expect(await tool.refreshSites()).toBe(true)
    expect(api.getDesign).toHaveBeenCalledOnce()
    expect(tool.isActive()).toBe(false)
  })

  it('rejects stale preview results after newer parameters and uses only the latest token', async () => {
    const { api } = setup()
    const old = deferred(), latest = deferred()
    api.previewClusterJoin.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    await tool.activate(); await choosePair()
    tool.updateParameters({ gap_nm: 1.5 })
    await vi.advanceTimersByTimeAsync(130)
    latest.resolve(validPreview({ preview_token: 'latest' }))
    await vi.advanceTimersByTimeAsync(0)
    old.resolve(validPreview({ preview_token: 'obsolete' }))
    await vi.advanceTimersByTimeAsync(0)
    expect(tool.getState().preview.preview_token).toBe('latest')
    await tool.apply()
    expect(api.applyClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ preview_token: 'latest', gap_nm: 1.5 }))
  })

  it('cancels previews on document replacement and cannot apply stale data', async () => {
    const { api, store, scene } = setup()
    const pending = deferred()
    api.previewClusterJoin.mockReturnValue(pending.promise)
    await tool.activate(); await choosePair()
    store.setState({ currentDesign: { id: 'other' } })
    pending.resolve(validPreview())
    await vi.advanceTimersByTimeAsync(0)
    expect(tool.isActive()).toBe(false)
    expect(scene.getObjectByName('cluster-join-preview').visible).toBe(false)
    expect(await tool.apply()).toBe(false)
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
  })

  it('releases picking and the preview when another CAD tool activates', async () => {
    const { store, scene } = setup()
    await tool.activate(); await choosePair()
    store.setState({ sweepActive: true })
    expect(tool.isActive()).toBe(false)
    expect(store.getState().joinActive).toBe(false)
    expect(scene.getObjectByName('cluster-join-ghost').children).toHaveLength(0)
    expect(document.querySelector('#cluster-join-panel').style.display).toBe('none')
  })

  it('refreshes metadata-only revision changes and keeps a failed preview from enabling Apply', async () => {
    const { api, setRevision } = setup()
    await tool.activate(); await choosePair()
    setRevision(8)
    api.getClusterJoinSites.mockResolvedValue({ ...catalog(), revision: 8 })
    api.previewClusterJoin.mockResolvedValue(validPreview({ revision: 8, preview_token: 'refreshed' }))
    expect(await tool.apply()).toBe(false)
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().preview.preview_token).toBe('refreshed')
    expect(tool.getState().first.id).toBe('a-side')
    api.previewClusterJoin.mockResolvedValue(validPreview({ revision: 8, valid: false, preview_token: null, errors: ['No legal scaffold splice'] }))
    tool.updateParameters({ tilt_deg: 15 })
    await vi.advanceTimersByTimeAsync(130)
    expect(document.querySelector('[data-join-apply]').disabled).toBe(true)
    expect(tool.getState().first.id).toBe('a-side')
  })

  it('keeps the popup and selected ports through a same-design save acknowledgement and refreshes its preview token', async () => {
    const { api, store, setRevision, design } = setup()
    await tool.activate(); await choosePair()
    setRevision(8)
    api.getClusterJoinSites.mockResolvedValue({ ...catalog(), revision: 8 })
    api.previewClusterJoin.mockResolvedValue(validPreview({ revision: 8, preview_token: 'after-save' }))
    store.setState({ currentDesign: { ...JSON.parse(JSON.stringify(design)), metadata: { identity_last_known_path: 'new-part.nadoc' }, feature_log: [{ id: 'metadata-history' }] } })
    expect(tool.isActive()).toBe(true)
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.getState().second.id).toBe('b-end')
    expect(document.querySelector('#cluster-join-panel').style.display).toBe('block')
    await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().preview.preview_token).toBe('after-save')
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
    await tool.apply()
    expect(api.applyClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ preview_token: 'after-save', expected_revision: 8 }))
  })

  it.each(['reset', 'escape'])('does not restore cancelled picks after a metadata refresh (%s)', async action => {
    const { api, store, setRevision, design } = setup()
    await tool.activate(); await choosePair()
    const fresh = deferred()
    api.getClusterJoinSites.mockReturnValue(fresh.promise)
    setRevision(8)
    store.setState({ currentDesign: { ...design, metadata: { identity_confirmed_at: 'saved' } } })
    expect(tool.getState().loading).toBe(true)
    if (action === 'reset') tool.reset()
    else window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(tool.getState().second).toBeNull()
    fresh.resolve({ ...catalog(), revision: 8 })
    await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().first?.id ?? null).toBe(action === 'reset' ? null : 'a-side')
    expect(tool.getState().second).toBeNull()
    expect(tool.getState().preview).toBeNull()
    expect(api.previewClusterJoin).toHaveBeenCalledOnce()
    expect(tool.isActive()).toBe(true)
  })

  it('deactivates for an actual native edit within the same document', async () => {
    const { store, design } = setup()
    await tool.activate(); await choosePair()
    store.setState({ currentDesign: { ...design, helices: [...design.helices, { id: 'new' }] } })
    expect(tool.isActive()).toBe(false)
    expect(await tool.apply()).toBe(false)
  })

  it('cannot reactivate from a retired asynchronous tool-start callback', async () => {
    const starting = deferred()
    const { api } = setup({ onActivate: () => starting.promise })
    const activation = tool.activate()
    tool.deactivate()
    starting.resolve(true)
    expect(await activation).toBe(false)
    expect(api.getClusterJoinSites).not.toHaveBeenCalled()
    expect(tool.isActive()).toBe(false)
  })

  it('reveals only nearby visible sites and lets actual mouse picks select them', async () => {
    const { canvas } = setup({ isSiteVisible: site => site.id !== 'a-end' })
    await tool.activate()
    const projected = tool.testApi.getSiteScreenPositions().find(site => site.id === 'a-side')
    const event = type => {
      const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: projected.x, clientY: projected.y, button: 0 })
      Object.defineProperty(e, 'pointerId', { value: 1 }); return e
    }
    canvas.dispatchEvent(event('pointermove'))
    expect(tool.getState().hoveredSiteId).toBe('a-side')
    expect(tool.getState().visibleSiteIds).not.toContain('a-end')
    canvas.dispatchEvent(event('pointerdown')); canvas.dispatchEvent(event('pointerup'))
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.testApi.getSiteScreenPositions().every(site => site.cluster_id === 'B')).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(tool.getState().first).toBe(null)
    expect(tool.isActive()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(tool.isActive()).toBe(false)
  })

  it('preserves an actual click when a metadata revision advances between hover and pointerdown', async () => {
    const { canvas, api, setRevision } = setup()
    await tool.activate()
    const point = tool.testApi.getSiteScreenPositions().find(site => site.id === 'a-side')
    const event = type => {
      const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: point.x, clientY: point.y, button: 0 })
      Object.defineProperty(e, 'pointerId', { value: 1 }); return e
    }
    canvas.dispatchEvent(event('pointermove'))
    expect(tool.getState().hoveredSiteId).toBe('a-side')
    const fresh = deferred()
    api.getClusterJoinSites.mockReturnValue(fresh.promise)
    setRevision(8)
    canvas.dispatchEvent(event('pointerdown')); canvas.dispatchEvent(event('pointerup'))
    expect(tool.getState().first).toBeNull()
    expect(tool.getState().loading).toBe(true)
    fresh.resolve({ ...catalog(), revision: 8 })
    await vi.advanceTimersByTimeAsync(0)
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.getState().revision).toBe(8)
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
  })

  it('does not sync an apply result into a different document', async () => {
    const { api, onApplied, store, setDocumentToken } = setup()
    const request = deferred()
    await tool.activate(); await choosePair()
    api.applyClusterJoin.mockReturnValue(request.promise)
    const applying = tool.apply()
    setDocumentToken('doc-B'); store.setState({ currentDesign: { id: 'part' } })
    request.resolve({ design: { id: 'part' }, revision: 8 })
    expect(await applying).toBe(false)
    expect(onApplied).not.toHaveBeenCalled()
  })
})

describe('Join screen projection', () => {
  it('excludes hidden sites, positions behind the camera and offscreen markers', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
    camera.position.set(0, 0, 20); camera.lookAt(0, 0, 0); camera.updateMatrixWorld()
    const points = [port('front', 'A', [0, 0, 0]), port('rear', 'B', [0, 0, 30]), port('offscreen', 'C', [100, 0, 0]), port('hidden', 'D', [0, 1, 0])]
    const result = nearbyJoinSites(points, { camera, rect: { left: 0, top: 0, width: 400, height: 400 }, clientX: 200, clientY: 200, isVisible: site => site.id !== 'hidden' })
    expect(result.map(item => item.site.id)).toEqual(['front'])
  })
})

describe('clearable selections and free movement', () => {
  it('clears either field independently and invalidates an in-flight preview', async () => {
    const { api } = setup()
    await tool.activate(); await choosePair()
    const pending = deferred(); api.previewClusterJoin.mockReturnValueOnce(pending.promise)
    tool.updateParameters({ gap_nm: 2 }); await vi.advanceTimersByTimeAsync(130)
    document.querySelector('[data-join-clear=first]').click()
    expect(tool.getState().first).toBeNull()
    expect(tool.getState().second.id).toBe('b-end')
    pending.resolve(validPreview()); await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().preview).toBeNull()
    expect(await tool.apply()).toBe(false)
    tool.testApi.pickSite('a-side'); await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().preview.valid).toBe(true)
    document.querySelector('[data-join-clear=second]').click()
    expect(tool.getState().first.id).toBe('a-side')
    expect(tool.getState().second).toBeNull()
  })

  it('previews the exact free pose, retires stale replies and commits once', async () => {
    const { api, store, design, scene } = setup()
    api.previewClusterJoin.mockResolvedValue(validPreview({ mode: 'free', connection_count: 3 }))
    await tool.activate()
    document.querySelector('[data-join-free]').click()
    expect(tool.testApi.pickCluster('B')).toBe(true)
    expect(scene.getObjectByName('join-movement-gizmo')).toBeTruthy()
    const pose = { world_translation: [-14, 2, 0], world_rotation: [0, 0, 0, 1] }
    tool.testApi.setFreePose(pose); await vi.advanceTimersByTimeAsync(130)
    expect(api.previewClusterJoin).toHaveBeenLastCalledWith(expect.objectContaining({ mode: 'free', moving_cluster_id: 'B', fixed_cluster_id: null, ...pose }), expect.anything())
    expect(store.getState().currentDesign).toBe(design)
    expect(document.querySelector('[data-join-report]').textContent).toContain('3 connections')
    const pending = deferred(); api.previewClusterJoin.mockReturnValueOnce(pending.promise)
    tool.testApi.setFreePose({ ...pose, world_translation: [-12, 2, 0] }); await vi.advanceTimersByTimeAsync(130)
    tool.testApi.setFreePose(pose)
    pending.resolve(validPreview({ connection_count: 99 })); await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().preview.connection_count).toBe(3)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(tool.getState().movementMode).toBe('rotate')
    const first = tool.apply(); const duplicate = tool.apply(); await Promise.all([first, duplicate])
    expect(api.applyClusterJoin).toHaveBeenCalledOnce()
    expect(api.applyClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ ...pose, mode: 'free', preview_token: 'token-1' }))
    expect(scene.getObjectByName('join-free-ghost').children).toHaveLength(0)
  })

  it('keeps a free pose through metadata refresh and cancels it without editing', async () => {
    const { store, design, api, setRevision, scene } = setup()
    await tool.activate(); tool.testApi.toggleFreeMovement(); tool.testApi.pickCluster('B')
    const pose = { world_translation: [-14, 2, 0], world_rotation: [0, 0, 0, 1] }
    tool.testApi.setFreePose(pose); await vi.advanceTimersByTimeAsync(130)
    setRevision(8); api.getClusterJoinSites.mockResolvedValue({ ...catalog(), revision: 8 })
    api.previewClusterJoin.mockResolvedValue(validPreview({ revision: 8 }))
    store.setState({ currentDesign: { ...design, metadata: { saved: true } } })
    await vi.advanceTimersByTimeAsync(130)
    expect(tool.getState().freePose).toEqual(pose)
    expect(api.previewClusterJoin).toHaveBeenLastCalledWith(expect.objectContaining({ ...pose, expected_revision: 8 }), expect.anything())
    document.querySelector('[data-join-clear=second]').click()
    expect(scene.getObjectByName('join-free-ghost').children).toHaveLength(0)
    expect(tool.getState().preview).toBeNull()
    tool.deactivate()
    expect(api.applyClusterJoin).not.toHaveBeenCalled()
    expect(store.getState().currentDesign.cluster_transforms).toEqual(design.cluster_transforms)
  })
})

it('shows saved unrouted joins after Apply and follows geometry, undo and document changes', () => {
  const { store, scene, design } = setup()
  const endpoint = (helix_id, bp_index) => ({ helix_id, bp_index, direction: 'FORWARD' })
  const constraint = { id: 'plan', first: { cluster_id: 'A', source: endpoint('a', 1), target: endpoint('a', 2) },
    second: { cluster_id: 'B', source: endpoint('b', 1), target: endpoint('b', 2) } }
  const geometry = ['a', 'b'].flatMap((h, i) => [1, 2].map(bp => ({ ...endpoint(h, bp), backbone_position: [i * 5, bp, 0] })))
  const saved = { ...design, cluster_join_constraints: [constraint] }
  store.setState({ currentDesign: saved, currentGeometry: geometry })
  const layer = scene.getObjectByName('cluster-join-constraints')
  expect(layer.children).toHaveLength(2)
  expect(tool.isActive()).toBe(false)
  expect(layer.children.every(line => line.material.isLineDashedMaterial)).toBe(true)
  store.setState({ currentGeometry: geometry.map(n => ({ ...n, backbone_position: n.backbone_position.map(v => v + 10) })) })
  expect(layer.children[0].geometry.attributes.position.getX(0)).toBe(10)
  store.setState({ currentDesign: design })
  expect(layer.children).toHaveLength(0)
  store.setState({ currentDesign: saved })
  expect(layer.children).toHaveLength(2)
  store.setState({ currentDesign: null })
  expect(layer.children).toHaveLength(0)
})

it('refreshes saved Join lines immediately from effective endpoint visibility without a server response', () => {
  const hidden = new Set()
  const key = endpoint => `${endpoint.helix_id}:${endpoint.bp_index}:${endpoint.direction}`
  const isSiteVisible = vi.fn(site => [site.from, site.to].every(endpoint => !hidden.has(key(endpoint))))
  const { store, scene, design, api } = setup({ isSiteVisible })
  const endpoint = (helix_id, bp_index) => ({ helix_id, bp_index, direction: 'FORWARD' })
  const constraint = { id: 'plan', first: { cluster_id: 'A', source: endpoint('a', 1), target: endpoint('a', 2) },
    second: { cluster_id: 'B', source: endpoint('b', 1), target: endpoint('b', 2) } }
  const geometry = ['a', 'b'].flatMap((h, i) => [1, 2].map(bp => ({ ...endpoint(h, bp), backbone_position: [i * 5, bp, 0] })))
  const saved = { ...design, cluster_join_constraints: [constraint] }
  store.setState({ currentDesign: saved, currentGeometry: geometry })
  const layer = scene.getObjectByName('cluster-join-constraints')
  expect(layer.children).toHaveLength(2)
  const lines = [...layer.children]
  const previous = lines.map(line => ({ line, geometry: line.geometry, material: line.material,
    disposeGeometry: vi.spyOn(line.geometry, 'dispose'), disposeMaterial: vi.spyOn(line.material, 'dispose') }))
  isSiteVisible.mockClear()
  hidden.add(key(constraint.first.source))
  tool.refreshVisibility()
  expect(layer.children).toEqual(lines)
  expect(lines.map(line => line.visible)).toEqual([false, true])
  expect(isSiteVisible).toHaveBeenCalledWith({ from: constraint.first.source, to: constraint.second.target })
  expect(isSiteVisible).toHaveBeenCalledWith({ from: constraint.second.source, to: constraint.first.target })
  for (const resource of previous) {
    expect(resource.line.geometry).toBe(resource.geometry)
    expect(resource.line.material).toBe(resource.material)
    expect(resource.disposeGeometry).not.toHaveBeenCalled()
    expect(resource.disposeMaterial).not.toHaveBeenCalled()
  }
  hidden.add(key(constraint.second.source)); tool.refreshVisibility()
  expect(lines.every(line => !line.visible)).toBe(true)
  hidden.clear(); tool.refreshVisibility()
  expect(layer.children).toEqual(lines)
  expect(lines.every(line => line.visible)).toBe(true)
  for (const resource of previous) {
    expect(resource.disposeGeometry).not.toHaveBeenCalled()
    expect(resource.disposeMaterial).not.toHaveBeenCalled()
  }
  expect(store.getState().currentDesign).toBe(saved)
  expect(store.getState().currentGeometry).toBe(geometry)
  expect(api.getClusterJoinSites).not.toHaveBeenCalled()
  expect(api.previewClusterJoin).not.toHaveBeenCalled()
  expect(api.applyClusterJoin).not.toHaveBeenCalled()
})

it('keeps placement-level saved Join hiding and makes visibility refresh inert after disposal', () => {
  const isSiteVisible = vi.fn(() => true)
  const { store, scene, design } = setup({ isSiteVisible })
  const endpoint = (helix_id, bp_index) => ({ helix_id, bp_index, direction: 'FORWARD' })
  const constraint = { id: 'plan', first: { cluster_id: 'A', source: endpoint('a', 1), target: endpoint('a', 2) },
    second: { cluster_id: 'B', source: endpoint('b', 1), target: endpoint('b', 2) } }
  const geometry = ['a', 'b'].flatMap((h, i) => [1, 2].map(bp => ({ ...endpoint(h, bp), backbone_position: [i * 5, bp, 0] })))
  store.setState({ currentDesign: { ...design, cluster_join_constraints: [constraint],
    visibility_state: { hidden_cluster_ids: ['A'] } }, currentGeometry: geometry })
  const layer = scene.getObjectByName('cluster-join-constraints')
  tool.refreshVisibility()
  expect(layer.children.filter(line => line.visible)).toHaveLength(0)
  isSiteVisible.mockClear()
  tool.dispose(); tool.refreshVisibility()
  expect(layer.children).toHaveLength(0)
  expect(scene.getObjectByName('cluster-join-constraints')).toBeUndefined()
  expect(isSiteVisible).not.toHaveBeenCalled()
})
