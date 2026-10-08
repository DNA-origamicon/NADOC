import { it, expect, vi } from 'vitest'
import { createFeatureAnimationDisplay, featureTopologySignature } from './feature_animation_display.js'
it('rebuilds historical topology even when it is absent from the editor, then restores the editor', () => {
  const renderer = { renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn() }
  const arcs = { refreshExternalGeometry: vi.fn() }
  const particles = { renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn() }
  const display = createFeatureAnimationDisplay({ getDesignRenderer: () => renderer, getUnfoldView: () => arcs, getNanoparticleRenderer: () => particles })
  const frame = n => ({ displayDesign: { strands: Array(n).fill({ id: 'historic' }) }, nucleotides: Array(n).fill({}),
    helixAxes: [], topologySignature: String(n) })
  const empty = frame(0), full = frame(2)
  expect(display.show(empty, full, 0)).toBe(true)
  expect(renderer.renderExternalGeometry.mock.lastCall[1]).toHaveLength(0)
  expect(display.show(empty, full, 0.2)).toBe(true)
  expect(renderer.renderExternalGeometry.mock.lastCall[1]).toHaveLength(2)
  expect(display.show(empty, full, 0.8)).toBe(false)
  expect(display.show(full, empty, 1)).toBe(true)
  expect(renderer.renderExternalGeometry.mock.lastCall[1]).toHaveLength(0)
  display.clear(); display.clear()
  expect(renderer.clearExternalGeometry).toHaveBeenCalledOnce()
  expect(particles.renderExternalGeometry).toHaveBeenLastCalledWith(empty.displayDesign, empty.nucleotides)
  expect(particles.clearExternalGeometry).toHaveBeenCalledOnce()
})
it('routing and sequence edits invalidate topology; pose-only changes do not', () => {
  const design = { strands: [{ id: 's', sequence: 'AAA', domains: [1] }] }
  expect(featureTopologySignature(design)).not.toBe(featureTopologySignature({ strands: [{ id: 's', sequence: 'AAA', domains: [2] }] }))
  expect(featureTopologySignature(design)).toBe(featureTopologySignature({ ...design, cluster_transforms: [1] }))
})
