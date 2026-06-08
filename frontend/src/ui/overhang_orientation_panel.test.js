// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// initOverhangGizmo builds real TransformControls (WebGL/DOM) → stub it. The stub
// captures setCallbacks so tests can drive onPreview, and lets getCurrentRDelta be
// overridden per test.
const gizmo = {
  attach: vi.fn(),
  detach: vi.fn(),
  setCallbacks: vi.fn((cb) => { gizmo._cb = cb }),
  getCurrentRDelta: vi.fn(() => new THREE.Quaternion()),
  accumulateDelta: vi.fn(),
  _cb: null,
}
vi.mock('../scene/overhang_gizmo.js', () => ({ initOverhangGizmo: () => gizmo }))
// design_queries lookups — keep simple deterministic answers.
vi.mock('../scene/design_queries.js', () => ({
  isExtrudeOverhang: (id) => id === 'ext',
  ovhgDomainIds: () => ['d1'],
}))

const { initOverhangOrientationPanel, buildOverhangRotationOps } =
  await import('./overhang_orientation_panel.js')

const OO_IDS = {
  'overhang-orient-panel': 'div', 'overhang-orient-info': 'div',
  'oo-apply-btn': 'button', 'oo-reset-btn': 'button', 'oo-cancel-btn': 'button',
  'oo-rx': 'input', 'oo-ry': 'input', 'oo-rz': 'input',
  'oo-rx-dec': 'button', 'oo-rx-inc': 'button',
  'oo-ry-dec': 'button', 'oo-ry-inc': 'button',
  'oo-rz-dec': 'button', 'oo-rz-inc': 'button',
}

function makeDeps(stateOverrides = {}) {
  const helixCtrl = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
  const store = createMockStore({
    currentDesign: {
      overhangs: [
        { id: 'a', label: 'Anchor', helix_id: 1, rotation: [0, 0, 0, 1], pivot: [1, 2, 3] },
        { id: 'b', label: '',       helix_id: 2, rotation: [0, 0, 0, 1], pivot: [4, 5, 6] },
      ],
    },
    assemblyActive: false,
    ...stateOverrides,
  })
  const deps = {
    store,
    api: { patchOverhangRotationsBatch: vi.fn().mockResolvedValue({}), getGeometry: vi.fn() },
    scene: {}, camera: {}, canvas: {}, controls: {},
    designRenderer: { getHelixCtrl: () => helixCtrl },
    bluntEnds: { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() },
    overhangLocations: { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() },
    assemblyRenderer: { invalidateInstance: vi.fn(), rebuild: vi.fn().mockResolvedValue() },
    getOvhgRootMap: () => new Map([
      ['a', { pos: new THREE.Vector3(1, 2, 3) }],
      ['b', { pos: new THREE.Vector3(4, 5, 6) }],
    ]),
  }
  return { deps, store, helixCtrl }
}

beforeEach(() => {
  clearDom()
  vi.clearAllMocks()
  gizmo.getCurrentRDelta.mockImplementation(() => new THREE.Quaternion())
})

describe('buildOverhangRotationOps (pure)', () => {
  const design = { overhangs: [
    { id: 'a', rotation: [0, 0, 0, 1] },
    { id: 'b', rotation: [0, 0, 0, 1] },
  ] }

  it('identity delta leaves existing rotation unchanged', () => {
    const ops = buildOverhangRotationOps(['a'], design, new THREE.Quaternion())
    expect(ops).toHaveLength(1)
    expect(ops[0].overhang_id).toBe('a')
    expect(ops[0].rotation).toEqual([0, 0, 0, 1])
  })

  it('composes the world delta onto each existing rotation', () => {
    const dz = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)
    const ops = buildOverhangRotationOps(['a'], design, dz)
    const [x, y, z, w] = ops[0].rotation
    expect(z).toBeCloseTo(Math.sin(Math.PI / 4), 6)
    expect(w).toBeCloseTo(Math.cos(Math.PI / 4), 6)
    expect(x).toBeCloseTo(0, 6)
    expect(y).toBeCloseTo(0, 6)
  })

  it('skips ids with no matching overhang', () => {
    const ops = buildOverhangRotationOps(['a', 'missing', 'b'], design, new THREE.Quaternion())
    expect(ops.map(o => o.overhang_id)).toEqual(['a', 'b'])
  })

  it('empty activeIds → []', () => {
    expect(buildOverhangRotationOps([], design, new THREE.Quaternion())).toEqual([])
  })

  it('null currentDesign → []', () => {
    expect(buildOverhangRotationOps(['a'], null, new THREE.Quaternion())).toEqual([])
  })

  it('baseRotations overrides the stored rotation per-id (Reset path)', () => {
    // A design where the stored rotation is non-identity, but the Reset baseline is
    // identity — an identity delta must yield identity ops, not the stored rotation.
    const dz = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)
    const rotated = { overhangs: [{ id: 'a', rotation: [dz.x, dz.y, dz.z, dz.w] }] }
    const ops = buildOverhangRotationOps(['a'], rotated, new THREE.Quaternion(), { a: [0, 0, 0, 1] })
    expect(ops[0].rotation[0]).toBeCloseTo(0, 6)
    expect(ops[0].rotation[1]).toBeCloseTo(0, 6)
    expect(ops[0].rotation[2]).toBeCloseTo(0, 6)
    expect(ops[0].rotation[3]).toBeCloseTo(1, 6)
  })

  it('falls back to the stored rotation when baseRotations lacks the id', () => {
    const ops = buildOverhangRotationOps(['a'], design, new THREE.Quaternion(), { other: [0, 0, 0, 1] })
    expect(ops[0].rotation).toEqual([0, 0, 0, 1])
  })
})

describe('initOverhangOrientationPanel (factory)', () => {
  it('open() shows the panel, labels a single overhang, and attaches the gizmo', () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    expect(document.getElementById('overhang-orient-panel').style.display).toBe('')
    expect(document.getElementById('overhang-orient-info').textContent).toBe('"Anchor"')
    expect(gizmo.attach).toHaveBeenCalledWith('a', ['a'], expect.any(Object), expect.any(THREE.Vector3))
    expect(panel.getActiveIds()).toEqual(['a'])
  })

  it('open() with no label falls back to the id; multi-select shows a count', () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['b'])
    expect(document.getElementById('overhang-orient-info').textContent).toBe('b')
    panel.open(['a', 'b'])
    expect(document.getElementById('overhang-orient-info').textContent).toBe('2 overhangs selected')
  })

  it('close() hides the panel, detaches the gizmo, and clears active ids', () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    panel.close()
    expect(document.getElementById('overhang-orient-panel').style.display).toBe('none')
    expect(gizmo.detach).toHaveBeenCalled()
    expect(panel.getActiveIds()).toEqual([])
    // not dirty → no client-side preview revert
    expect(deps.api.getGeometry).not.toHaveBeenCalled()
  })

  it('close() re-fetches geometry only after a preview made the panel dirty', () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    // a gizmo drag preview marks dirty
    deps.gizmoCb().onPreview(new THREE.Quaternion())
    panel.close()
    expect(deps.api.getGeometry).toHaveBeenCalledTimes(1)
  })

  it('Apply commits composed rotation ops then closes', async () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const dz = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)
    gizmo.getCurrentRDelta.mockImplementation(() => dz.clone())
    const panel = panelWith(deps)
    panel.open(['a', 'b'])
    document.getElementById('oo-apply-btn').click()
    await Promise.resolve(); await Promise.resolve()
    expect(deps.api.patchOverhangRotationsBatch).toHaveBeenCalledTimes(1)
    const ops = deps.api.patchOverhangRotationsBatch.mock.calls[0][0]
    expect(ops.map(o => o.overhang_id)).toEqual(['a', 'b'])
    expect(panel.getActiveIds()).toEqual([])   // closed
  })

  it('Reset previews to identity client-side — no server patch (commits only on Apply)', async () => {
    mountIds(OO_IDS)
    const { deps, helixCtrl } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a', 'b'])
    gizmo.attach.mockClear()
    document.getElementById('oo-reset-btn').click()
    await Promise.resolve(); await Promise.resolve()
    // No server round-trip on Reset itself.
    expect(deps.api.patchOverhangRotationsBatch).not.toHaveBeenCalled()
    // Previewed client-side (per-overhang transform applied).
    expect(helixCtrl.applyClusterTransform).toHaveBeenCalled()
    // Gizmo re-attached at the cached junction pivot (bug 1: must pass the pivot,
    // not fall back to [0,0,0]).
    expect(gizmo.attach).toHaveBeenCalledWith('a', ['a', 'b'], expect.any(Object), expect.any(THREE.Vector3))
  })

  it('Reset then Cancel adds NO feature-log entry (no patch) and reverts the preview', async () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a', 'b'])
    document.getElementById('oo-reset-btn').click()
    await Promise.resolve(); await Promise.resolve()
    document.getElementById('oo-cancel-btn').click()
    expect(deps.api.patchOverhangRotationsBatch).not.toHaveBeenCalled()
    expect(deps.api.getGeometry).toHaveBeenCalledTimes(1)   // preview reverted
    expect(panel.getActiveIds()).toEqual([])                // closed
  })

  it('Reset then Apply commits identity for every active overhang', async () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a', 'b'])
    document.getElementById('oo-reset-btn').click()
    await Promise.resolve(); await Promise.resolve()
    document.getElementById('oo-apply-btn').click()
    await Promise.resolve(); await Promise.resolve()
    expect(deps.api.patchOverhangRotationsBatch).toHaveBeenCalledTimes(1)
    const ops = deps.api.patchOverhangRotationsBatch.mock.calls[0][0]
    expect(ops).toEqual([
      { overhang_id: 'a', rotation: [0, 0, 0, 1] },
      { overhang_id: 'b', rotation: [0, 0, 0, 1] },
    ])
  })

  it('a ±45° step button previews incrementally (accumulates into the gizmo)', () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    document.getElementById('oo-rx-inc').click()
    expect(gizmo.accumulateDelta).toHaveBeenCalledTimes(1)
    const q = gizmo.accumulateDelta.mock.calls[0][0]
    // +45° about X
    expect(q.x).toBeCloseTo(Math.sin(Math.PI / 8), 6)
    expect(q.w).toBeCloseTo(Math.cos(Math.PI / 8), 6)
  })

  it('Apply with no active overhangs is a no-op (no patch)', async () => {
    mountIds(OO_IDS)
    const { deps } = makeDeps()
    panelWith(deps)
    document.getElementById('oo-apply-btn').click()
    await Promise.resolve()
    expect(deps.api.patchOverhangRotationsBatch).not.toHaveBeenCalled()
  })

  it('auto-closes when the overhang set changes while editing', () => {
    mountIds(OO_IDS)
    const { deps, store } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    // structural change: drop overhang 'b' → set changed
    store.setState({ currentDesign: { overhangs: [
      { id: 'a', label: 'Anchor', helix_id: 1, rotation: [0, 0, 0, 1], pivot: [1, 2, 3] },
    ] } })
    expect(panel.getActiveIds()).toEqual([])
    expect(document.getElementById('overhang-orient-panel').style.display).toBe('none')
  })

  it('does NOT auto-close on a pure rotation patch (same id set)', () => {
    mountIds(OO_IDS)
    const { deps, store } = makeDeps()
    const panel = panelWith(deps)
    panel.open(['a'])
    store.setState({ currentDesign: { overhangs: [
      { id: 'a', label: 'Anchor', helix_id: 1, rotation: [0, 0, 0.7, 0.7], pivot: [1, 2, 3] },
      { id: 'b', label: '',       helix_id: 2, rotation: [0, 0, 0, 1],     pivot: [4, 5, 6] },
    ] } })
    expect(panel.getActiveIds()).toEqual(['a'])
  })
})

// Wire the factory, exposing the captured gizmo callbacks on deps for the dirty-preview test.
function panelWith(deps) {
  const p = initOverhangOrientationPanel(deps)
  deps.gizmoCb = () => gizmo._cb
  return p
}
