import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { initSettingsDialog } from './dialog.js'
import { readPreferences } from './preferences.js'
let dialog
const clickText = text => [...document.querySelectorAll('button')].find(el => el.textContent === text).click()
beforeEach(() => { localStorage.clear(); document.body.innerHTML = '<button id="menu-file-settings">Settings</button>' })
afterEach(() => { dialog?.dispose(); vi.restoreAllMocks() })
it('opens all ten categories with no simulation workflow tab and cancels live text preview', () => {
  dialog = initSettingsDialog({ api: {} }); dialog.open()
  expect(document.querySelectorAll('[role=tab]')).toHaveLength(10)
  expect([...document.querySelectorAll('[role=tab]')].map(el => el.textContent).join(' ')).not.toContain('Simulation')
  const input = document.getElementById('setting-textScale'); input.value = '1.5'; input.dispatchEvent(new Event('input'))
  expect(document.documentElement.style.getPropertyValue('--text-base')).toBe('22.5px')
  clickText('Cancel')
  expect(readPreferences().textScale).toBe(1)
  expect(document.documentElement.style.getPropertyValue('--text-base')).toBe('15px')
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('validates changed server paths before applying any preferences', async () => {
  const api = { getMdRunDirStatus: vi.fn().mockResolvedValue({ ok: false, detail: 'Unavailable' }) }
  dialog = initSettingsDialog({ api }); dialog.open()
  const input = document.querySelector('[aria-label="MD / NAMD storage folder"]'); input.value = '/missing'; input.dispatchEvent(new Event('input'))
  clickText('Apply'); await vi.waitFor(() => expect(document.querySelector('.settings-status').textContent).toContain('Unavailable'))
  expect(localStorage.getItem('nadoc.runDir.namd')).toBeNull()
  expect(localStorage.getItem('nadoc:preferences:v1')).toBeNull()
})
it('persists applied preferences and reopens them; tab arrows move focus', async () => {
  dialog = initSettingsDialog({ api: {} }); dialog.open()
  const input = document.getElementById('setting-textScale'); input.value = '1.25'; input.dispatchEvent(new Event('input'))
  clickText('Apply'); await vi.waitFor(() => expect(readPreferences().textScale).toBe(1.25))
  clickText('Cancel'); dialog.open()
  expect(document.getElementById('setting-textScale').value).toBe('1.25')
  const tab = document.getElementById('settings-tab-appearance'); tab.focus(); tab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  expect(document.activeElement.id).toBe('settings-tab-storage')
  expect(document.getElementById('settings-panel-storage').hidden).toBe(false)
})

it('places the Settings command in File, including with no document open', async () => {
  const { default: markup } = await import('../../index.html?raw')
  const html = new DOMParser().parseFromString(markup, 'text/html')
  const command = html.getElementById('menu-file-settings')
  expect(command.closest('.menu-item').querySelector(':scope > button').textContent).toBe('File')
  expect(command.disabled).toBe(false)
})
