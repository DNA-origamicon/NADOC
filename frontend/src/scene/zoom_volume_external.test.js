import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildZoomExternal } from './zoom_volume_external.js'

it('isolates an external object and retains local bounds under an assembly transform', async () => {
  const root = new THREE.Group(); root.position.x = 100
  const layer = await buildZoomExternal({ root, design: { nanoparticles: [
    { id: 'wanted', kind: 'gold', diameter_nm: 4 }, { id: 'other', kind: 'gold', diameter_nm: 20 },
  ] }, refs: [{ kind: 'nanoparticle', id: 'wanted' }], representation: 'full', coloring: 'strand', opacity: .5,
  signal: new AbortController().signal, proteinData: vi.fn() })
  expect(layer.count).toBe(1)
  expect(root.children).toHaveLength(1)
  expect(layer.bounds.min.x).toBeCloseTo(-2)
  expect(layer.bounds.max.x).toBeCloseTo(2)
  expect(root.children[0].material.opacity).toBe(.5)
  layer.dispose(); expect(root.children).toHaveLength(0)
})
