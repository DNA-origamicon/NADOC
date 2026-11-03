import { it, expect, vi } from 'vitest'
import { enumerateCylinders } from '../design/yggdnasil_cylinders.js'
import { showYggDNAsil } from './yggdnasil.js'
it('selects concrete structures, follows radius neighbors, and disposes the 3D view', () => {
  const viewer = { update: vi.fn(), reset: vi.fn(), dispose: vi.fn() }
  const modal = showYggDNAsil({ viewerFactory: () => viewer })
  try {
    expect(showYggDNAsil()).toBe(modal)
    expect(modal.root.querySelector('[data-status]').textContent).toContain('unique footprints')
    const picker = modal.root.querySelector('[data-node]')
    picker.value = picker.options[0].value; picker.dispatchEvent(new Event('change'))
    expect(modal.root.querySelector('h2').textContent).toBe('1hb × 100 bp')
    modal.root.querySelector('[data-step=next]').click()
    expect(modal.root.querySelector('h2').textContent).not.toBe('1hb × 100 bp')
    expect(viewer.update.mock.lastCall[0].length).toBe(100)
    const reserve = modal.root.querySelector('[data-reserve]')
    reserve.value = '7248'; reserve.dispatchEvent(new Event('change'))
    expect(modal.root.querySelector('.ygg-detail').textContent).toContain('No footprints')
    reserve.value = '0'; reserve.dispatchEvent(new Event('change'))
    expect(modal.root.querySelector('h2')).not.toBeNull()
    modal.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(modal.isOpen()).toBe(false)
    expect(viewer.dispose).toHaveBeenCalledTimes(1)
  } finally { modal.close() }
})
it('keeps a usable selector when WebGL is unavailable', () => {
  const modal = showYggDNAsil({ viewerFactory: () => { throw new Error('No GPU') } })
  try {
    expect(modal.root.querySelector('[data-tree-view]').textContent).toContain('3D rendering is unavailable')
    expect(modal.root.querySelector('[data-node]').options.length).toBeGreaterThan(0)
  } finally { modal.close() }
})
it('shows curvature on every eligible junction without a separate explore mode', () => {
  const viewer = { update: vi.fn(), reset: vi.fn(), dispose: vi.fn() }
  const modal = showYggDNAsil({ viewerFactory: () => viewer })
  try {
    const picker = modal.root.querySelector('[data-node]')
    picker.value = [...picker.options].find(o => o.textContent.startsWith('4hb')).value
    picker.dispatchEvent(new Event('change'))
    const rootId = picker.value
    expect(modal.root.querySelector('[data-branch]')).toBeNull()
    expect(modal.root.querySelector('[data-explore-curvature]')).toBeNull()
    expect(modal.root.querySelector('[data-curve-summary]').textContent).toContain('0.00°')
    modal.root.querySelector('[data-step=bend-next]').click()
    expect(picker.value).not.toBe(rootId)
    expect(viewer.update.mock.lastCall[0].branchCount).toBeGreaterThan(1)
    const last = viewer.update.mock.lastCall[0].nodes.filter(n => n.rootId === rootId).at(-1)
    picker.value = last.id; picker.dispatchEvent(new Event('change'))
    expect(modal.root.querySelector('[data-curve-summary]').textContent).toContain('360.00°')
    modal.root.querySelector('[data-straight]').click()
    expect(picker.value).toBe(rootId)
    expect(modal.root.querySelector('[data-filter]').disabled).toBe(false)
  } finally { modal.close() }
})

it('offers straight hollow branches with separate inner-radius navigation', () => {
  const viewer = { update: vi.fn(), reset: vi.fn(), dispose: vi.fn() }
  const modal = showYggDNAsil({ viewerFactory: () => viewer })
  try {
    const shape = modal.root.querySelector('[data-shape]'); shape.value = 'hollow'; shape.dispatchEvent(new Event('change'))
    const model = viewer.update.mock.lastCall[0]
    expect(model.nodes.length).toBeGreaterThan(0)
    expect(model.nodes.every(n => n.shape === 'hollow' && !n.curvature && !n.routing.excluded)).toBe(true)
    expect(modal.root.querySelector('[data-hollow-summary]').textContent).toContain('0°')
    expect(modal.root.querySelector('[data-step=bend-next]')).toBeNull()
    const edge = model.edges.find(e => e.parameter === 'inner-radius'), picker = modal.root.querySelector('[data-node]')
    picker.value = edge.from; picker.dispatchEvent(new Event('change'))
    modal.root.querySelector('[data-step=inner-next]').click()
    expect(picker.value).toBe(edge.to)
  } finally { modal.close() }
})

it('ignores obsolete cylinder worker responses and terminates workers on close', () => {
  const pending = []
  class WorkerDouble {
    constructor() { pending.push(this) }
    postMessage = vi.fn()
    terminate = vi.fn()
  }
  vi.stubGlobal('Worker', WorkerDouble)
  const viewer = { update: vi.fn(), dispose: vi.fn(), reset: vi.fn() }
  const modal = showYggDNAsil({ viewerFactory: () => viewer })
  try {
    const length = modal.root.querySelector('[data-tree-length]')
    length.value = '120'; length.dispatchEvent(new Event('change'))
    expect(pending[0].terminate).toHaveBeenCalled()
    const calls = viewer.update.mock.calls.length
    pending[0].onmessage({ data: { atlas: enumerateCylinders() } })
    expect(viewer.update.mock.calls).toHaveLength(calls)
    pending[1].onmessage({ data: { atlas: enumerateCylinders({ length: 120 }) } })
    expect(viewer.update.mock.lastCall[0].nodes.every(n => n.length === 120)).toBe(true)
    length.value = '110'; length.dispatchEvent(new Event('change'))
    modal.close()
    expect(pending[2].terminate).toHaveBeenCalled()
    const after = viewer.update.mock.calls.length
    pending[2].onmessage({ data: { atlas: enumerateCylinders({ length: 110 }) } })
    expect(viewer.update.mock.calls).toHaveLength(after)
  } finally { modal.close(); vi.unstubAllGlobals() }
})
