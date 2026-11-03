import { it, expect, vi } from 'vitest'
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
