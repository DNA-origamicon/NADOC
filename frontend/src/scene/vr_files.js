import { createVRTextKeyboard, TEXT_KEY_ROWS } from './vr_text_keyboard.js'
import { openFileBrowser } from '../ui/file_browser.js'

export const FILE_ACTIONS = [
  ['file-new', 'New Part'], ['file-assembly', 'New Assembly'],
  ['file-open', 'Open'], ['file-save', 'Save As'], ['file-close', 'Close Session'],
]

export const FILE_KEY_ROWS = TEXT_KEY_ROWS

export function fileTableDetail(row) {
  const d = row.dataset, size = d.vrFileSize === '' || d.vrFileSize == null ? NaN : Number(d.vrFileSize)
  const date = new Date(d.vrFileModified)
  const bytes = !Number.isFinite(size) || size < 0 ? '--' : size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`
  return [d.vrFileType || '--', Number.isNaN(date.getTime()) ? '--' : date.toISOString().slice(0, 10), bytes].join('|')
}

// File operations remain browser-owned. Native only sends versioned selections.
export function createVRFiles({ doc = document, api, newPart, openPart, openAssembly,
  saveAs, closeSession, refresh = async () => {}, beforeSwitch = async () => true, onError = console.error } = {}) {
  let active = false, busy = false, error = '', keyboard = false
  const textKeyboard = createVRTextKeyboard()
  let task = Promise.resolve()
  const run = fn => {
    busy = true; error = ''
    task = Promise.resolve().then(fn).catch(e => { error = e.message; onError(error) }).finally(() => { busy = false })
  }
  async function refreshScene() {
    if (await refresh() === null) throw new Error('File opened, but the VR scene could not refresh. Retry from File.')
  }
  function start(id) {
    active = true; keyboard = id === 'file-new'; textKeyboard.reset()
    run(async () => {
      if (id === 'file-new') { if (await beforeSwitch()) newPart(() => { run(async () => { await refreshScene(); active = false }) }); else active = false }
      if (id === 'file-save') await saveAs()
      if (id === 'file-close') { await closeSession(); active = false }
      if (id === 'file-open') {
        const result = await openFileBrowser({ title: 'Open File', mode: 'open', fileType: 'part', api })
        if (result && await beforeSwitch()) {
          let file = result
          if (file.peer_id) {
            const checkout = await api.checkoutPeerLibraryFile(file.peer_id, file.path)
            if (!checkout?.path) throw new Error('Could not open shared file')
            file = checkout
          }
          if (/\.nass$/i.test(file.path)) await openAssembly(file.path)
          else if (await openPart(file.path, file.name) === false) throw new Error('Could not open part')
          await refreshScene()
        }
        active = false
      }
    })
  }
  function snapshot() {
    const browser = doc.querySelector('[data-vr-file-browser]')
    const switchFileAction = async id => {
      if (browser) {
        const previous = task
        browser.querySelector('[data-vr-file-action=Cancel]')?.click()
        await previous
      }
      start(id)
    }
    const roots = FILE_ACTIONS.map(([id, label]) => ({ id, label, enabled: id !== 'file-assembly' && (!active || !!browser), active: false, run: () => switchFileAction(id) }))
    if (!active) return { roots, title: '', controls: [] }
    const modal = [...doc.querySelectorAll('.modal__overlay')].find(el => el.querySelector('#new-design-name'))
    const input = modal?.querySelector('#new-design-name') || browser?.querySelector('[data-vr-filename]')
    const controls = []
    const add = (id, label, fn, enabled = true, selected = false, detail = '') => controls.push({ id, label, enabled, active: selected, run: fn, ...(detail ? { detail } : {}) })
    if (modal || browser) {
      if (input && keyboard) {
        controls.push(...textKeyboard.controls(input, { prefix: 'file-key-', maxLength: 120 }))
        add('info-filename', input.value || 'Enter filename', null, false)
        if (browser) add('file-browse', 'Folders', () => { keyboard = false })
      } else if (browser) {
        controls.push(...roots)
        for (const [i, row] of [...browser.querySelectorAll('[data-vr-file-row]')].entries()) add(`file-entry-${i}`, row.dataset.vrFileName || row.dataset.vrFileRow, () => row.click(), true, false, fileTableDetail(row))
        if (input) add('file-keyboard', 'Filename: ' + input.value, () => { input.setSelectionRange(input.value.length, input.value.length); keyboard = true })
      }
      const buttons = modal ? [...modal.querySelectorAll('button')].filter(b => /^(Cancel|Create)$/.test(b.textContent.trim())) : [...browser.querySelectorAll('[data-vr-file-action]')]
      const uniqueButtons = buttons.filter((b, i) => buttons.findIndex(other => (other.dataset.vrFileAction || other.textContent.trim()) === (b.dataset.vrFileAction || b.textContent.trim())) === i)
      const errorText = browser?.querySelector('[data-vr-file-error]')
      if (errorText && errorText.style.display !== 'none' && errorText.textContent) add('info-error', errorText.textContent, null, false)
      if (browser && !keyboard) add('info-location', browser.querySelector('[data-vr-file-location]')?.textContent || 'Workspace', null, false)
      uniqueButtons.forEach((button, i) => add(`file-button-${i}`, button.dataset.vrFileAction || button.textContent.trim(), () => { if (modal && button.textContent.trim() === 'Create') input.value = input.value.trim().replace(/\.nadoc$/i, ''); button.click(); if (/^(Cancel|Close)$/.test(button.dataset.vrFileAction || button.textContent.trim())) active = false }, !button.disabled && (!/^(Create|Save)$/.test(button.textContent.trim()) || !!input?.value.trim())))
      return { roots, title: input && keyboard ? 'Filename keyboard' : 'Open / Save File', controls }
    }
    add('dismiss', busy ? 'Please wait...' : 'Done', () => { active = false; error = '' }, !busy)
    add('info-file', error || (busy ? 'Working...' : 'Finished'), null, false)
    return { roots, title: 'File', controls }
  }
  return { snapshot, reset() { textKeyboard.reset(); active = false; keyboard = false; error = '' } }
}

/** Do not replace an active document if its save failed or was cancelled. */
export async function saveBeforeVRFileSwitch({ store, api, fileIo, workspacePath, assemblyPath }) {
  const state = store.getState()
  let result = true
  if (state.assemblyActive) result = assemblyPath ? await api.saveAssemblyAs(assemblyPath) : await api.saveAssemblyToWorkspace()
  else if (state.currentDesign) result = workspacePath ? await fileIo.saveToWorkspace(workspacePath) : await fileIo.saveAs()
  if (!result) throw new Error('Current document was not saved. File operation cancelled.')
  return true
}
