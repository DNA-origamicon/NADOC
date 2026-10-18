import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPartComparisonSurface } from './part_comparison_surface.js'
import { comparisonBinding, comparisonEnvelope } from '../test-helpers/part_comparison.js'

const surfaces = []
function setup() {
  const host = document.createElement('div'); document.body.append(host)
  let state = { open: false, busy: false, projection: null, binding: null, error: null, issues: [] }
  const listeners = new Set(), viewers = []
  const controller = { getState: () => state,
    subscribe: fn => { listeners.add(fn); fn(state); return () => listeners.delete(fn) }, close: vi.fn() }
  const createViewer = vi.fn(() => { const viewer = { dispose: vi.fn(), resetView: vi.fn() }; viewers.push(viewer); return viewer })
  const surface = createPartComparisonSurface({ host, controller, createViewer }); surfaces.push(surface)
  const change = patch => { state = { ...state, ...patch }; for (const fn of listeners) fn(state) }
  return { host, controller, change, createViewer, surface, listeners, viewers }
}
afterEach(() => { for (const surface of surfaces.splice(0)) surface.dispose(); document.body.replaceChildren() })

describe('comparison surface never installs a live design', () => {
  it('labels published authoring as unverified, proposed geometry as evaluated, and excluded layers explicitly', () => {
    const h = setup(), packet = comparisonEnvelope(), binding = comparisonBinding()
    expect(h.createViewer).not.toHaveBeenCalled()
    h.change({ open: true, projection: packet, binding })
    expect(h.host.textContent).toMatch(/Published authored geometry.*unverified/i)
    expect(h.host.textContent).toMatch(/Evaluated proposal/i)
    expect(h.host.textContent).toMatch(/physical.*presentation.*excluded/i)
    expect(h.host.textContent).toMatch(/all authored placements/i)
    expect(h.host.textContent).toMatch(/unplaced.*unused/i)
    expect(h.createViewer).toHaveBeenCalledExactlyOnceWith(expect.any(HTMLElement), packet, binding)
    expect(h.host.textContent).not.toMatch(/last good|physically validated/i)
  })

  it('disposes both panes together when source/job/lease invalidates and never leaves a partial comparison', () => {
    const h = setup()
    h.change({ open: true, projection: comparisonEnvelope(), binding: comparisonBinding() })
    h.change({ projection: null, error: new Error('The comparison expired'), issues: [] })
    expect(h.viewers[0].dispose).toHaveBeenCalledOnce()
    expect(h.host.textContent).toMatch(/expired/i)
    expect(h.createViewer).toHaveBeenCalledOnce()
  })

  it('shows an unsupported diagnostic without allocating a scene or hiding it behind a source-only model', () => {
    const h = setup()
    h.change({ open: true, error: new Error('Comparison does not yet cover helices'),
      issues: [{ code: 'unsupported_comparison_scope', detail: 'Comparison does not yet cover helices' }] })
    expect(h.host.textContent).toContain('Comparison does not yet cover helices')
    expect(h.createViewer).not.toHaveBeenCalled()
  })

  it('reports a display initialization failure without showing a partial model or mutating the repair', () => {
    const h = setup()
    h.createViewer.mockImplementationOnce(() => { throw new Error('WebGL unavailable') })
    expect(() => h.change({ open: true, projection: comparisonEnvelope(), binding: comparisonBinding() })).not.toThrow()
    expect(h.host.textContent).toContain('WebGL unavailable')
    expect(h.controller.close).not.toHaveBeenCalled()
    expect(h.host.querySelector('canvas')).toBeNull()
  })

  it('clears the viewer on close and unsubscribes on unmount without cancelling the evaluated repair', () => {
    const h = setup()
    h.change({ open: true, projection: comparisonEnvelope(), binding: comparisonBinding() })
    h.change({ open: false, projection: null })
    expect(h.viewers[0].dispose).toHaveBeenCalledOnce()
    h.surface.dispose(); h.surface.dispose()
    expect(h.listeners.size).toBe(0)
    expect(h.host.children).toHaveLength(0)
    expect(h.controller.close).not.toHaveBeenCalled()
  })
})
