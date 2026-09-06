import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { initGrapheneNanoporeOverlay } from './graphene_nanopore_overlay.js'

describe('graphene nanopore preview', () => {
  it('draws a registered sheet and clears it', () => {
    const scene = new THREE.Scene()
    const view = initGrapheneNanoporeOverlay(scene)
    view.update({ enabled: true, poreDiameterNm: 2.1,
      surface: { dir: [0, 1, 0], positionNm: -2 },
      bounds: { min: [-4, -1, -3], max: [4, 1, 3] } })
    expect(view.mesh()?.name).toBe('Graphene nanopore preview')
    expect(view.mesh()?.position.y).toBeCloseTo(-2)
    expect(view.mesh()?.geometry.getAttribute('position').count).toBeGreaterThan(8)
    view.clear()
    expect(view.mesh()).toBeNull()
  })
})

it('suppresses the design preview throughout MD display, including preview edits', () => {
  const view = initGrapheneNanoporeOverlay(new THREE.Scene())
  const spec = { enabled: true, surface: { dir: [0, 1, 0], positionNm: -2 } }
  view.update(spec)
  view.setSimulationActive(true)
  expect(view.mesh().visible).toBe(false)
  view.update(spec)
  expect(view.mesh().visible).toBe(false)
  view.setSimulationActive(false)
  expect(view.mesh().visible).toBe(true)
  view.dispose()
})
