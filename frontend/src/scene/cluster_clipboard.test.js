import * as THREE from 'three'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockStore } from '../test-helpers/mock_store.js'
import { initClusterClipboard } from './cluster_clipboard.js'

const AXES = {
  h_XY_0_0: { start: [0, 0, 0], end: [0, 0, 34], samples: null },
  h_XY_0_2: { start: [5, 0, 0], end: [5, 0, 34], samples: null },
}

const DESIGN = {
  lattice_type: 'HONEYCOMB',
  helices: [
    { id: 'h_XY_0_0', grid_pos: [0, 0] },
    { id: 'h_XY_0_2', grid_pos: [0, 2] },
  ],
  cluster_transforms: [
    { id: 'cA', helix_ids: ['h_XY_0_0'], parent_cluster_id: null },
    { id: 'cChild', helix_ids: ['h_XY_0_0'], parent_cluster_id: 'cA' },
    { id: 'cB', helix_ids: ['h_XY_0_2'], parent_cluster_id: null },
  ],
}

function setup(stateOverrides = {}) {
  const store = createMockStore({
    currentDesign: DESIGN,
    currentHelixAxes: AXES,
    selectedObject: null,
    multiSelectedClusterIds: [],
    ...stateOverrides,
  })
  const scene = new THREE.Scene()
  const slicePlane = {
    showPlacement: vi.fn(),
    disarmPlacement: vi.fn(),
  }
  const api = { pasteClusters: vi.fn().mockResolvedValue({ paste_report: {}, pasteReport: {} }) }
  const showToast = vi.fn()
  const clipboard = initClusterClipboard({ store, api, scene, slicePlane, showToast })
  return { clipboard, store, scene, slicePlane, api, showToast }
}

const selectCluster = (id) => ({ selectedObject: { type: 'cluster', id } })

describe('copy', () => {
  it('refuses when nothing is selected', () => {
    const { clipboard, showToast } = setup()
    expect(clipboard.copy()).toBe(false)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Select a cluster'), expect.anything())
  })

  it('copies the single selected cluster', () => {
    const { clipboard, showToast } = setup(selectCluster('cB'))
    expect(clipboard.copy()).toBe(true)
    expect(showToast).toHaveBeenCalledWith('Copied 1 cluster (1 helices)')
  })

  it('pulls in a child cluster and says so', () => {
    const { clipboard, showToast } = setup(selectCluster('cA'))
    expect(clipboard.copy()).toBe(true)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('pulled in 1 linked cluster'))
  })

  it('reads the multi-select cluster pool', () => {
    const { clipboard, showToast } = setup({ multiSelectedClusterIds: ['cB'] })
    expect(clipboard.copy()).toBe(true)
    expect(showToast).toHaveBeenCalledWith('Copied 1 cluster (1 helices)')
  })

  it('refuses at Ctrl+C when a copied helix carries an overhang', () => {
    // Learn now, not after aiming a ghost at a cell.
    const { clipboard, showToast } = setup({
      ...selectCluster('cB'),
      currentDesign: { ...DESIGN, overhangs: [{ id: 'o1', helix_id: 'h_XY_0_2' }] },
    })
    expect(clipboard.copy()).toBe(false)
    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining('1 overhang'),
      expect.objectContaining({ severity: 'error' }),
    )
  })

  it('a refused copy leaves the clipboard empty so Ctrl+V does nothing', () => {
    const { clipboard, slicePlane } = setup({
      ...selectCluster('cB'),
      currentDesign: { ...DESIGN, overhangs: [{ id: 'o1', helix_id: 'h_XY_0_2' }] },
    })
    clipboard.copy()
    expect(clipboard.paste()).toBe(false)
    expect(slicePlane.showPlacement).not.toHaveBeenCalled()
  })
})

describe('paste', () => {
  it('refuses with an empty clipboard', () => {
    const { clipboard, slicePlane, showToast } = setup()
    expect(clipboard.paste()).toBe(false)
    expect(slicePlane.showPlacement).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Nothing copied yet'), expect.anything())
  })

  it('arms the slice-plane ghost with the footprint and the phase-parity snap', () => {
    const { clipboard, slicePlane } = setup(selectCluster('cB'))
    clipboard.copy()
    expect(clipboard.paste()).toBe(true)

    const [plane, spec] = slicePlane.showPlacement.mock.calls[0]
    expect(plane).toBe('XY')
    expect(spec.cells).toEqual([[0, 2]])
    expect(spec.anchorCell).toEqual([0, 2])
    expect(spec.commitKind).toBe('cluster-paste')
    expect(typeof spec.candidateCells).toBe('function')
    expect(typeof spec.onGhostUpdate).toBe('function')
  })

  it('adds a ghost mesh to the scene and marks itself active', () => {
    const { clipboard, scene } = setup(selectCluster('cB'))
    clipboard.copy()
    expect(clipboard.isActive()).toBe(false)
    clipboard.paste()
    expect(clipboard.isActive()).toBe(true)
    expect(scene.children).toHaveLength(1)
    expect(scene.children[0].children).toHaveLength(1)  // one tube per copied helix
  })

  it('moves the ghost to the offset and reddens it on conflict', () => {
    const { clipboard, slicePlane, scene } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    const { onGhostUpdate } = slicePlane.showPlacement.mock.calls[0][1]
    const ghost = scene.children[0]

    onGhostUpdate({ worldOffset: new THREE.Vector3(1, 2, 3), conflict: false, gridDelta: [0, 4] })
    expect(ghost.visible).toBe(true)
    expect(ghost.position.toArray()).toEqual([1, 2, 3])
    const freeColor = ghost.children[0].material.color.getHex()

    onGhostUpdate({ worldOffset: new THREE.Vector3(1, 2, 3), conflict: true, gridDelta: [0, 2] })
    expect(ghost.children[0].material.color.getHex()).not.toBe(freeColor)
  })

  it('hides the ghost when the cursor leaves the lattice', () => {
    const { clipboard, slicePlane, scene } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    slicePlane.showPlacement.mock.calls[0][1].onGhostUpdate(null)
    expect(scene.children[0].visible).toBe(false)
  })
})

describe('onCommit', () => {
  it('posts the closure ids and the grid delta', async () => {
    const { clipboard, api } = setup(selectCluster('cA'))
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 4] })

    expect(api.pasteClusters).toHaveBeenCalledWith({
      clusterIds: ['cA', 'cChild'],  // closure, in design order
      deltaRow: 0,
      deltaCol: 4,
    })
  })

  it('tears the ghost down after a successful paste', async () => {
    const { clipboard, scene, slicePlane } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 4] })

    expect(clipboard.isActive()).toBe(false)
    expect(scene.children).toHaveLength(0)
    expect(slicePlane.disarmPlacement).toHaveBeenCalled()
  })

  it('surfaces the backend rejection reason when the paste is refused', async () => {
    // Regression: `_request` sets store.lastError but never toasts, so swallowing the
    // null response made a 400 look identical to "the click did nothing".
    const { clipboard, api, store, showToast } = setup(selectCluster('cB'))
    api.pasteClusters.mockResolvedValue(null)
    store.setState({ lastError: { status: 400, message: 'cluster selection carries 4 overhang(s)' } })
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 4] })

    expect(showToast).toHaveBeenCalledWith(
      'cluster selection carries 4 overhang(s)',
      expect.objectContaining({ severity: 'error' }),
    )
  })

  it('falls back to a generic message when lastError is empty', async () => {
    const { clipboard, api, showToast } = setup(selectCluster('cB'))
    api.pasteClusters.mockResolvedValue(null)
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 4] })
    expect(showToast).toHaveBeenCalledWith('Paste failed.', expect.objectContaining({ severity: 'error' }))
  })

  it('keeps the ghost armed after a failed paste so the user can retry elsewhere', async () => {
    const { clipboard, api, scene } = setup(selectCluster('cB'))
    api.pasteClusters.mockResolvedValue(null)
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 2] })

    expect(clipboard.isActive()).toBe(true)
    expect(scene.children).toHaveLength(1)
  })

  it('a failed paste does not wedge the committing latch', async () => {
    const { clipboard, api } = setup(selectCluster('cB'))
    api.pasteClusters.mockResolvedValueOnce(null)
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 2] })

    api.pasteClusters.mockResolvedValue({ pasteReport: { closure_cluster_ids: ['cB'] } })
    await clipboard.onCommit({ gridDelta: [0, 4] })
    expect(api.pasteClusters).toHaveBeenCalledTimes(2)
    expect(clipboard.isActive()).toBe(false)
  })

  it('reports truncated strands', async () => {
    const { clipboard, api, showToast } = setup(selectCluster('cB'))
    api.pasteClusters.mockResolvedValue({
      pasteReport: { closure_cluster_ids: ['cB'], truncated_strand_count: 3 },
    })
    clipboard.copy()
    clipboard.paste()
    await clipboard.onCommit({ gridDelta: [0, 4] })
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('3 strands truncated'))
  })

  it('is a no-op with an empty clipboard', async () => {
    const { clipboard, api } = setup()
    await clipboard.onCommit({ gridDelta: [0, 4] })
    expect(api.pasteClusters).not.toHaveBeenCalled()
  })
})

describe('cancel / lifecycle', () => {
  it('disposes the ghost and disarms the slice plane', () => {
    const { clipboard, scene, slicePlane } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    clipboard.cancel()

    expect(clipboard.isActive()).toBe(false)
    expect(scene.children).toHaveLength(0)
    expect(slicePlane.disarmPlacement).toHaveBeenCalled()
  })

  it('drops a live ghost when the design changes underneath it (undo, load)', () => {
    const { clipboard, store, scene } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    expect(clipboard.isActive()).toBe(true)

    store.setState({ currentDesign: { ...DESIGN } })  // new object identity
    expect(clipboard.isActive()).toBe(false)
    expect(scene.children).toHaveLength(0)
  })

  it('does not drop the ghost on an unrelated state change', () => {
    const { clipboard, store } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    store.setState({ someOtherKey: 1 })
    expect(clipboard.isActive()).toBe(true)
  })

  it('re-pasting replaces the previous ghost rather than stacking one', () => {
    const { clipboard, scene } = setup(selectCluster('cB'))
    clipboard.copy()
    clipboard.paste()
    clipboard.paste()
    expect(scene.children).toHaveLength(1)
  })
})
