import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { vi } from 'vitest'

vi.mock('../api/client.js', () => ({ putNucleotideTransform: vi.fn() }))

import { putNucleotideTransform } from '../api/client.js'
import { abstractPreviewUpdate, abstractResidueInfo, initNucleotideTransformTool, transformBodyForTarget } from './nucleotide_transform_tool.js'

describe('transformBodyForTarget', () => {
  const pivot = new THREE.Vector3(1, 2, 3)
  const translation = new THREE.Vector3(0.5, -1, 2)
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)

  it('serializes an ordinary/loop nucleotide identity', () => {
    expect(transformBodyForTarget(
      { helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 2 },
      pivot, translation, q,
    )).toMatchObject({
      kind: 'base', helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy_k: 2,
      pivot: [1, 2, 3], translation: [0.5, -1, 2], compose: true,
    })
  })

  it('captures the exact source bead-to-slab arrangement for full-representation rebuilds', () => {
    const beadMatrix = new THREE.Matrix4().makeTranslation(1, 2, 3)
    const slabQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 0.4)
    const slabMatrix = new THREE.Matrix4().compose(
      new THREE.Vector3(1.2, 2.3, 3.4), slabQ, new THREE.Vector3(0.3, 0.06, 0.7))
    const body = transformBodyForTarget(
      { helix_id: 'h1', bp_index: 7, direction: 'FORWARD' }, pivot, translation, q,
      { beadMatrix, slabMatrix },
    )
    expect(body.display_slab_offset).toEqual(expect.arrayContaining([
      expect.closeTo(0.2), expect.closeTo(0.3), expect.closeTo(0.4),
    ]))
    expect(body.display_slab_rotation).toHaveLength(4)
  })

  it('serializes a crossover-extra-base identity', () => {
    expect(transformBodyForTarget(
      { helix_id: '__xb__', crossover_id: 'xo:with:colons', k: 1 },
      pivot, translation, q,
    )).toMatchObject({
      kind: 'extra_base', crossover_id: 'xo:with:colons', extra_base_k: 1,
      pivot: [1, 2, 3], translation: [0.5, -1, 2], compose: true,
    })
  })
})

describe('abstract nucleotide projection', () => {
  const nuc = {
    helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 0,
    backbone_position: [1, 0, 0], base_position: [0, 1, 0],
    base_normal: [1, 0, 0], axis_tangent: [0, 0, 1],
  }

  it('finds the same selected residue in full geometry', () => {
    const info = abstractResidueInfo(
      { helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 0 }, [nuc])
    expect(info.nuc).toBe(nuc)
    expect(info.centroid.toArray()).toEqual([1, 0, 0])
  })

  it('previews the same rigid delta on the bead and nucleotide frame', () => {
    const info = { nuc, centroid: new THREE.Vector3(1, 0, 0) }
    const matrix = new THREE.Matrix4().makeRotationZ(Math.PI / 2)
    const update = abstractPreviewUpdate(info, matrix)
    expect(update.backbone_position[0]).toBeCloseTo(0)
    expect(update.backbone_position[1]).toBeCloseTo(1)
    const beforeOffset = new THREE.Vector3(...nuc.base_position)
      .sub(new THREE.Vector3(...nuc.backbone_position))
    const afterOffset = new THREE.Vector3(...update.base_position)
      .sub(new THREE.Vector3(...update.backbone_position))
    expect(afterOffset.length()).toBeCloseTo(beforeOffset.length())
    expect(update.nx).toBeCloseTo(0)
    expect(update.ny).toBeCloseTo(1)
    expect(update.tz).toBeCloseTo(1)
  })
})

describe('atomistic transform commit', () => {
  it('keeps the optimistic residue pose and lets the design subscriber own the sole rebuild', async () => {
    document.body.innerHTML = '<div id="mode-indicator"></div>'
    const selected = { helix_id: '__xb__', crossover_id: 'xo1', k: 0 }
    const store = {
      getState: () => ({ multiSelectedBaseKeys: ['__xb__:xo1:0'] }),
    }
    const atomisticRenderer = {
      getMode: () => 'ballstick',
      residueInfo: vi.fn(() => ({ centroid: new THREE.Vector3(1, 2, 3) })),
      applyResidueMatrix: vi.fn(),
    }
    let finishCommit
    putNucleotideTransform.mockReturnValueOnce(new Promise(resolve => { finishCommit = resolve }))
    const obsoleteExplicitRefresh = vi.fn()
    const tool = initNucleotideTransformTool({
      store,
      scene: new THREE.Scene(),
      camera: new THREE.PerspectiveCamera(),
      canvas: document.createElement('canvas'),
      controls: { enabled: true },
      designRenderer: {}, atomisticRenderer,
      // Deliberately supplied as the old API did. It must no longer be consulted.
      refreshAtomistic: obsoleteExplicitRefresh,
    })

    expect(tool.activate()).toBe(true)
    const committing = tool.confirm()
    // confirm() used to apply identity here, visibly snapping to the pre-move pose.
    expect(atomisticRenderer.applyResidueMatrix).not.toHaveBeenCalled()
    finishCommit({ design: { nucleotide_transforms: [{ target: selected }] } })
    await committing
    expect(atomisticRenderer.applyResidueMatrix).not.toHaveBeenCalled()
    expect(obsoleteExplicitRefresh).not.toHaveBeenCalled()
  })
})
