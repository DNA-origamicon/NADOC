import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearShortcuts, registerShortcut } from '../input/shortcuts.js'
import { initAccessibility, populateShortcutHelp, shortcutWorkflows } from './accessibility.js'

describe('accessibility wiring', () => {
  beforeEach(() => {
    clearShortcuts()
    document.body.innerHTML = `
      <div id="menu-bar"><div class="menu-item"><button>File</button><div class="dropdown"><button id="open">Open</button></div></div></div>
      <canvas id="canvas">3D design workspace</canvas>
      <h2 id="camera-panel-heading" style="cursor:pointer"></h2>
      <div id="help-modal"><div class="hk-body"></div></div><button id="menu-help-hotkeys"></button>`
  })

  it('opens a top-level menu and moves focus into it from the keyboard', () => {
    initAccessibility()
    const file = document.querySelector('.menu-item > button')
    file.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(file.getAttribute('aria-expanded')).toBe('true')
    expect(document.activeElement.id).toBe('open')
  })

  it('labels and focuses the 3D workspace and keyboard-enables panel headings', () => {
    initAccessibility()
    const canvas = document.getElementById('canvas')
    expect(canvas.getAttribute('aria-label')).toContain('3D molecular design')
    expect(canvas.tabIndex).toBe(0)
    const heading = document.getElementById('camera-panel-heading')
    const click = vi.fn()
    heading.addEventListener('click', click)
    heading.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(click).toHaveBeenCalledOnce()
  })

  it('keyboard-enables clickable rows added by panels after startup', async () => {
    const a11y = initAccessibility()
    const row = document.createElement('div')
    row.style.cursor = 'pointer'
    const click = vi.fn()
    row.addEventListener('click', click)
    document.body.appendChild(row)
    await Promise.resolve()
    expect(row.getAttribute('role')).toBe('button')
    expect(row.tabIndex).toBe(0)
    row.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    expect(click).toHaveBeenCalledOnce()
    a11y.destroy()
  })

  it('renders shortcut help from the production registry', () => {
    registerShortcut({ key: 'z', ctrl: true, description: 'Undo', handler() {} })
    populateShortcutHelp()
    expect(document.querySelector('.hk-desc').textContent).toBe('Undo')
    expect(document.querySelector('.hk-key').textContent).toBe('Ctrl Z')
  })

  it('clusters shortcuts by workflow across two columns', () => {
    const groups = shortcutWorkflows([
      { key: 'F1', ctrl: false, description: 'Representation: Full' },
      { key: '2', ctrl: false, description: 'Full Autostaple' },
      { key: 'e', ctrl: false, description: 'Cycle selectable forward' },
      { key: 'g', ctrl: false, description: 'Toggle grid' },
    ])
    expect(groups.map(group => group.title)).toEqual([
      'Representations', 'Automation & sequencing', 'Selection', 'View & display',
    ])
    for (const shortcut of [
      { key: 'F1', description: 'Representation: Full' },
      { key: '2', description: 'Full Autostaple' },
    ]) registerShortcut({ ...shortcut, handler() {} })
    populateShortcutHelp()
    expect(document.querySelectorAll('.hk-column')).toHaveLength(2)
    expect([...document.querySelectorAll('.hk-section-title')].map(el => el.textContent))
      .toEqual(['Representations', 'Automation & sequencing'])
  })
})
