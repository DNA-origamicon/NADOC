import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initJointPick } from './joint_pick.js'

// Minimal store stub: getState() returns the provided snapshot.
function makeStore(state) {
  return { getState: () => state }
}

// designRenderer stub: getBackboneEntries returns the supplied entries.
function makeRenderer(entries) {
  return { getBackboneEntries: () => entries }
}

function rectCanvas() {
  // 200×100 viewport at origin.
  return { getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 100 }) }
}

describe('initJointPick.canvasNdc', () => {
  const jp = initJointPick({
    canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
    store: makeStore({}), designRenderer: makeRenderer([]),
  })

  it('maps the viewport center to (0, 0)', () => {
    const ndc = jp.canvasNdc({ clientX: 100, clientY: 50 })
    expect(ndc.x).toBeCloseTo(0, 6)
    expect(ndc.y).toBeCloseTo(0, 6)
  })

  it('maps top-left to (-1, +1) and bottom-right to (+1, -1)', () => {
    const tl = jp.canvasNdc({ clientX: 0, clientY: 0 })
    expect(tl.x).toBeCloseTo(-1, 6)
    expect(tl.y).toBeCloseTo(1, 6)
    const br = jp.canvasNdc({ clientX: 200, clientY: 100 })
    expect(br.x).toBeCloseTo(1, 6)
    expect(br.y).toBeCloseTo(-1, 6)
  })
})

describe('initJointPick.clusterBackboneEntries', () => {
  const entries = [
    { nuc: { helix_id: 0 } },
    { nuc: { helix_id: 1 } },
    { nuc: { helix_id: 2 } },
  ]

  it('defaults the entry list from designRenderer.getBackboneEntries', () => {
    const jp = initJointPick({
      canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
      store: makeStore({}), designRenderer: makeRenderer(entries),
    })
    const out = jp.clusterBackboneEntries({ helix_ids: [1] }, {})
    expect(out).toEqual([{ nuc: { helix_id: 1 } }])
  })

  it('honors an explicit entry list over the renderer default', () => {
    const jp = initJointPick({
      canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
      store: makeStore({}), designRenderer: makeRenderer(entries),
    })
    const explicit = [{ nuc: { helix_id: 5 } }]
    const out = jp.clusterBackboneEntries({ helix_ids: [5] }, {}, explicit)
    expect(out).toEqual(explicit)
  })

  it('tolerates a renderer without getBackboneEntries (empty default)', () => {
    const jp = initJointPick({
      canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
      store: makeStore({}), designRenderer: {},
    })
    expect(jp.clusterBackboneEntries({ helix_ids: [0] }, {})).toEqual([])
  })
})

describe('initJointPick.pickActiveClusterEntry', () => {
  it('returns null when there is no active cluster', () => {
    const jp = initJointPick({
      canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
      store: makeStore({ activeClusterId: null, currentDesign: { cluster_transforms: [] } }),
      designRenderer: makeRenderer([]),
    })
    expect(jp.pickActiveClusterEntry({ clientX: 100, clientY: 50 })).toBeNull()
  })

  it('returns null when the active cluster has no backbone entries', () => {
    const jp = initJointPick({
      canvas: rectCanvas(), camera: new THREE.PerspectiveCamera(),
      store: makeStore({
        activeClusterId: 'c1',
        currentDesign: { cluster_transforms: [{ id: 'c1', helix_ids: [0] }] },
      }),
      designRenderer: makeRenderer([]),
    })
    expect(jp.pickActiveClusterEntry({ clientX: 100, clientY: 50 })).toBeNull()
  })

  it('raycasts the active cluster meshes and returns the hit entry', () => {
    // Camera at +Z looking down -Z; an instanced bead at the origin sits dead
    // center, so a center-of-viewport pick should hit it.
    const camera = new THREE.PerspectiveCamera(50, 2, 0.1, 100)
    camera.position.set(0, 0, 5)
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld(true)

    const geom = new THREE.SphereGeometry(1, 16, 16)
    const mat = new THREE.MeshBasicMaterial()
    const instMesh = new THREE.InstancedMesh(geom, mat, 1)
    instMesh.setMatrixAt(0, new THREE.Matrix4().identity())
    instMesh.instanceMatrix.needsUpdate = true
    instMesh.updateMatrixWorld(true)

    const entry = { id: 0, instMesh, nuc: { helix_id: 0 } }
    const jp = initJointPick({
      canvas: rectCanvas(), camera,
      store: makeStore({
        activeClusterId: 'c1',
        currentDesign: { cluster_transforms: [{ id: 'c1', helix_ids: [0] }] },
      }),
      designRenderer: makeRenderer([entry]),
    })

    const hit = jp.pickActiveClusterEntry({ clientX: 100, clientY: 50 })
    expect(hit).toBe(entry)
  })

  it('skips hidden meshes (no hit when the only mesh is invisible)', () => {
    const camera = new THREE.PerspectiveCamera(50, 2, 0.1, 100)
    camera.position.set(0, 0, 5)
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld(true)

    const geom = new THREE.SphereGeometry(1, 16, 16)
    const instMesh = new THREE.InstancedMesh(geom, new THREE.MeshBasicMaterial(), 1)
    instMesh.setMatrixAt(0, new THREE.Matrix4().identity())
    instMesh.instanceMatrix.needsUpdate = true
    instMesh.updateMatrixWorld(true)
    instMesh.visible = false

    const entry = { id: 0, instMesh, nuc: { helix_id: 0 } }
    const jp = initJointPick({
      canvas: rectCanvas(), camera,
      store: makeStore({
        activeClusterId: 'c1',
        currentDesign: { cluster_transforms: [{ id: 'c1', helix_ids: [0] }] },
      }),
      designRenderer: makeRenderer([entry]),
    })

    expect(jp.pickActiveClusterEntry({ clientX: 100, clientY: 50 })).toBeNull()
  })
})
