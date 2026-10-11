import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { showTJunctionHelp } from './t_junction_help.js'

let dialog
const change = (selector, value, type = 'change') => {
  const node = document.querySelector(selector)
  node.value = value
  node.dispatchEvent(new Event(type, { bubbles: true }))
  return node
}
const makeViewer = () => {
  const viewer = { update: vi.fn(), resetView: vi.fn(), dispose: vi.fn() }
  const factory = vi.fn(host => {
    const canvas = document.createElement('canvas')
    canvas.tabIndex = 0
    host.append(canvas)
    return viewer
  })
  return { viewer, factory }
}
beforeEach(() => { document.body.innerHTML = '<button id="launch">Open junction preview</button><div id="design">Existing document</div>' })
afterEach(() => { dialog?.close(); dialog = null; document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('T-junction Help preview', () => {
  it('opens without a current design and changes real model geometry from presets and sliders', () => {
    const { viewer, factory } = makeViewer()
    dialog = showTJunctionHelp({ viewerFactory: factory })
    expect(factory).toHaveBeenCalledOnce()
    expect(dialog.root.getAttribute('aria-labelledby')).toBeTruthy()
    expect(document.querySelectorAll('[data-preset]')).toHaveLength(5)
    expect(dialog.getModel().helices).toHaveLength(12)
    const before = dialog.getModel().helices.find(h => h.bundle === 'branch').end
    document.querySelector('[data-preset="acute"]').click()
    expect(dialog.getModel().params.angleDeg).toBe(60)
    expect(dialog.getModel().helices.find(h => h.bundle === 'branch').end).not.toEqual(before)
    change('[data-param="attachment"]', '0.72', 'input')
    expect(dialog.getModel().params.attachment).toBe(0.72)
    expect(document.querySelector('[data-readout="attachment"]').textContent).toContain('72%')
    expect(document.querySelectorAll('[data-preset][aria-pressed="true"]')).toHaveLength(0)
    document.querySelector('[data-preset="spatial"]').click()
    expect(dialog.getModel().params).toMatchObject({ angleDeg: 90, azimuthDeg: 45, attachment: 0.5 })
    expect(viewer.update).toHaveBeenCalled()
    expect(viewer.resetView).toHaveBeenCalledTimes(2)
    expect(document.getElementById('design').textContent).toBe('Existing document')
  })

  it('switches the actual routing stage and renderer representation', () => {
    const { viewer, factory } = makeViewer()
    dialog = showTJunctionHelp({ viewerFactory: factory })
    expect(dialog.getModel().routes).toHaveLength(1)
    expect(dialog.getModel().bridges).toHaveLength(2)
    change('[data-control="stage"]', 'separate')
    expect(dialog.getModel().routes).toHaveLength(2)
    expect(dialog.getModel().bridges).toHaveLength(0)
    expect(document.querySelector('[data-tjunction-metrics]').textContent).toContain('2 scaffold cycles')
    change('[data-control="representation"]', 'scaffold')
    expect(viewer.update.mock.calls.at(-1)[1].representation).toBe('scaffold')
    const highlight = document.querySelector('[data-control="highlight"]')
    highlight.checked = false
    highlight.dispatchEvent(new Event('change', { bubbles: true }))
    expect(viewer.update.mock.calls.at(-1)[1].highlightBridges).toBe(false)
    change('[data-control="stage"]', 'joined')
    expect(dialog.getModel().routes).toHaveLength(1)
    expect(document.querySelector('[data-tjunction-metrics]').textContent).toContain('1 scaffold cycle')
  })

  it('traps keyboard focus, suppresses editor shortcuts, closes with Escape, and restores the launcher', () => {
    const launcher = document.getElementById('launch')
    launcher.focus()
    const { viewer, factory } = makeViewer()
    dialog = showTJunctionHelp({ viewerFactory: factory })
    const first = dialog.root.querySelector('button')
    const last = dialog.actions.querySelector('button')
    first.focus()
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(last)
    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(first)
    const editorShortcut = vi.fn()
    window.addEventListener('keydown', editorShortcut)
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }))
    expect(editorShortcut).not.toHaveBeenCalled()
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(dialog.isOpen()).toBe(false)
    expect(document.activeElement).toBe(launcher)
    expect(viewer.dispose).toHaveBeenCalledOnce()
    dialog.close()
    expect(viewer.dispose).toHaveBeenCalledOnce()
    window.removeEventListener('keydown', editorShortcut)
  })

  it('reuses one open dialog and creates fresh disposable resources after close', () => {
    const { viewer, factory } = makeViewer()
    dialog = showTJunctionHelp({ viewerFactory: factory })
    const duplicate = showTJunctionHelp({ viewerFactory: factory })
    expect(duplicate).toBe(dialog)
    expect(factory).toHaveBeenCalledOnce()
    dialog.close()
    dialog = showTJunctionHelp({ viewerFactory: factory })
    expect(factory).toHaveBeenCalledTimes(2)
    dialog.overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(dialog.isOpen()).toBe(false)
    expect(viewer.dispose).toHaveBeenCalledTimes(2)
  })

  it('keeps the explanation and close control usable if WebGL is unavailable', () => {
    dialog = showTJunctionHelp({ viewerFactory: () => { throw new Error('WebGL unavailable') } })
    expect(dialog.root.querySelector('[role="alert"]').textContent).toContain('WebGL unavailable')
    expect(dialog.root.textContent).toContain('One scaffold connection pair')
    expect(dialog.root.querySelector('a[href^="https://doi.org/"]')).not.toBeNull()
    change('[data-param="angleDeg"]', '120', 'input')
    expect(dialog.getModel().params.angleDeg).toBe(120)
    dialog.close()
    expect(dialog.isOpen()).toBe(false)
  })
})
