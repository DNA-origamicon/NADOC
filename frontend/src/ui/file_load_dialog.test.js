import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initFileLoadDialog } from './file_load_dialog.js'

function mount() {
  return mountIds({
    'file-load-progress': 'div',
    'flp-fill': 'div',
    'flp-status': 'div',
    'flp-header': 'div',
    'flp-log': 'div',
    'flp-log-wrap': 'div',
    'flp-details-toggle': 'button',
    'flp-actions': 'div',
  })
}

describe('initFileLoadDialog', () => {
  beforeEach(() => clearDom())

  it('show() resets the overlay and makes it visible', () => {
    const els = mount()
    els['flp-log'].innerHTML = '<div>stale</div>'
    els['flp-log-wrap'].style.display = 'block'
    const dlg = initFileLoadDialog()
    dlg.show('Opening Part')
    expect(els['file-load-progress'].classList.contains('visible')).toBe(true)
    expect(els['flp-header'].textContent).toBe('Opening Part')
    expect(els['flp-log'].innerHTML).toBe('')
    expect(els['flp-log-wrap'].style.display).toBe('none')
    expect(els['flp-details-toggle'].textContent).toBe('▸ Details')
    expect(els['flp-actions'].style.display).toBe('none')
    expect(els['flp-fill'].style.width).toBe('0%')
  })

  it('hide() removes the visible class', () => {
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.show('x')
    dlg.hide()
    expect(els['file-load-progress'].classList.contains('visible')).toBe(false)
  })

  it('setProgress() sets fill width and status text', () => {
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.setProgress(50, 'Importing…')
    expect(els['flp-fill'].style.width).toBe('50%')
    expect(els['flp-status'].textContent).toBe('Importing…')
  })

  it('appendLog() appends a coloured line and scrolls', () => {
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.appendLog('hello')
    dlg.appendLog('boom', 'error')
    const lines = els['flp-log'].querySelectorAll('div')
    expect(lines.length).toBe(2)
    expect(lines[0].textContent).toMatch(/^\[\+\d+\.\ds\] hello$/)
    expect(lines[0].style.color).toBe('rgb(139, 148, 158)') // info
    expect(lines[1].style.color).toBe('rgb(248, 81, 73)')   // error
  })

  it('expandDetails() opens the log pane', () => {
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.expandDetails()
    expect(els['flp-log-wrap'].style.display).toBe('block')
    expect(els['flp-details-toggle'].textContent).toBe('▾ Details')
  })

  it('showError() paints red, expands details, shows actions', () => {
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.showError('Could not load part.')
    expect(els['flp-status'].textContent).toBe('Could not load part.')
    expect(els['flp-fill'].style.width).toBe('100%')
    expect(els['flp-log-wrap'].style.display).toBe('block')
    expect(els['flp-actions'].style.display).toBe('flex')
  })

  it('showSuccess() fills green then hides after the delay', async () => {
    vi.useFakeTimers()
    const els = mount()
    const dlg = initFileLoadDialog()
    dlg.show('x')
    const p = dlg.showSuccess('"Part" loaded')
    expect(els['flp-status'].textContent).toBe('"Part" loaded')
    expect(els['flp-fill'].style.width).toBe('100%')
    expect(els['file-load-progress'].classList.contains('visible')).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    await p
    expect(els['file-load-progress'].classList.contains('visible')).toBe(false)
    vi.useRealTimers()
  })

  it('details-toggle button flips the log pane open/closed', () => {
    const els = mount()
    initFileLoadDialog()
    els['flp-details-toggle'].click()
    expect(els['flp-log-wrap'].style.display).toBe('block')
    expect(els['flp-details-toggle'].textContent).toBe('▾ Details')
    els['flp-details-toggle'].click()
    expect(els['flp-log-wrap'].style.display).toBe('none')
    expect(els['flp-details-toggle'].textContent).toBe('▸ Details')
  })

  it('shows elapsed time, freezes it on success, and copies a report', async () => {
    vi.useFakeTimers()
    const els = mountIds({
      'file-load-progress': 'div', 'flp-fill': 'div', 'flp-status': 'div',
      'flp-header': 'div', 'flp-log': 'div', 'flp-log-wrap': 'div',
      'flp-details-toggle': 'button', 'flp-actions': 'div',
      'flp-elapsed': 'div', 'flp-copy': 'button',
    })
    const writeText = vi.fn().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const dlg = initFileLoadDialog()
    dlg.show('Opening Part')
    dlg.appendLog('fetched design')
    vi.advanceTimersByTime(2000)
    expect(els['flp-elapsed'].textContent).toBe('elapsed 2.0s')
    const done = dlg.showSuccess('Loaded')
    vi.advanceTimersByTime(1500)
    await done
    expect(els['flp-elapsed'].textContent).toBe('elapsed 2.0s')
    els['flp-copy'].click()
    await vi.advanceTimersByTimeAsync(0)
    const text = writeText.mock.calls[0][0]
    expect(text).toContain('Operation: Opening Part')
    expect(text).toContain('Elapsed: 2.0s')
    expect(text).toMatch(/\[\+0\.0s\] fetched design/)
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })
})
