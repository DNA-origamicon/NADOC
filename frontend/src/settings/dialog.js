import './settings.css'
import { CATEGORIES, FIELDS, DEFAULTS, readPreferences, writePreferences, importPreferences, exportPreferences } from './preferences.js'
import { shortcutId, formatShortcut, validateShortcutConflicts } from './shortcut_bindings.js'
import { notificationHistory, clearNotificationHistory } from './notification_history.js'
import { applyAppearance } from './appearance.js'
import { createModal } from '../ui/primitives/modal.js'
import { createButton } from '../ui/primitives/button.js'
import { pickSystemFolder } from '../ui/folder_picker.js'
import { getRunDir, RUN_DIR_EVENT } from '../ui/run_location_preferences.js'
import { clearRecentFiles } from '../api/recent_files.js'
import { getShortcutDefinitions } from '../input/shortcuts.js'

const node = (tag, text, className) => {
  const result = document.createElement(tag)
  if (text) result.textContent = text
  if (className) result.className = className
  return result
}
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const link = node('a'); link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function initSettingsDialog({ api, menuButton = document.getElementById('menu-file-settings') }) {
  let modal = null
  function open() {
    if (modal?.isOpen()) return
    let saved = readPreferences()
    let draft = { ...saved }
    let busy = false
    const focusBefore = document.activeElement
    const paths = { namd: getRunDir('namd') || '', oxdna: getRunDir('oxdna') || '' }
    const originalPaths = { ...paths }
    const controls = new Map()
    const pathInputs = new Map()
    const panels = new Map()
    const tabs = new Map()
    let active = 'appearance'
    const body = node('div')
    const search = node('input', null, 'settings-search')
    search.type = 'search'; search.placeholder = 'Find a setting…'; search.setAttribute('aria-label', 'Find a setting')
    const layout = node('div', null, 'settings-layout')
    const tablist = node('div', null, 'settings-tabs'); tablist.setAttribute('role', 'tablist'); tablist.setAttribute('aria-label', 'Settings categories'); tablist.setAttribute('aria-orientation', 'vertical')
    const content = node('div', null, 'settings-panels')
    const status = node('div', null, 'settings-status'); status.setAttribute('role', 'status')
    body.append(search, layout, status); layout.append(tablist, content)
    const activate = id => {
      active = id
      for (const [key, panel] of panels) panel.hidden = key !== id
      for (const [key, tab] of tabs) { tab.setAttribute('aria-selected', String(key === id)); tab.tabIndex = key === id ? 0 : -1 }
    }
    for (const [id, label] of CATEGORIES) {
      const tab = createButton({ label, onClick: () => activate(id) })
      tab.id = `settings-tab-${id}`; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', `settings-panel-${id}`)
      const panel = node('section', null, 'settings-panel'); panel.id = `settings-panel-${id}`; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id)
      panel.append(node('h2', label)); tabs.set(id, tab); panels.set(id, panel); tablist.append(tab); content.append(panel)
    }
    tablist.addEventListener('keydown', event => {
      const list = [...tabs.values()].filter(tab => !tab.hidden)
      const index = list.indexOf(document.activeElement)
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? list.length - 1 : ['ArrowDown', 'ArrowRight'].includes(event.key) ? (index + 1) % list.length : ['ArrowUp', 'ArrowLeft'].includes(event.key) ? (index + list.length - 1) % list.length : -1
      if (next >= 0) { event.preventDefault(); list[next].click(); list[next].focus() }
    })
    const note = (category, text) => panels.get(category).append(node('p', text, 'settings-note'))
    note('appearance', 'This browser. Text size previews immediately; Cancel restores the saved appearance.')
    note('storage', `Folders are on the NADOC server (${location.host}), not the browser computer. These browser defaults apply to new jobs. Existing files and running jobs retain their locations. Empty means the workspace default.`)
    note('saving', 'Autosave writes the complete part or assembly to its existing workspace file after editing pauses. Session recovery remains active independently. Save File is always available.')
    note('layout', 'Layout persistence changes take effect on the next reload. Current documents remain open.')
    note('viewport', 'Display preferences only. Molecular geometry and topology are unchanged.')
    note('navigation', 'Sensitivity applies to the current navigation controls. Existing simulation workflow settings are unchanged.')
    note('editor', 'Selection defaults apply in both part and assembly editors. Construction parameters and feature history remain document-owned.')
    note('notifications', 'These preferences affect application messages. Explicitly timed messages retain their own duration.')
    for (const [key, field] of Object.entries(FIELDS)) {
      if (field.type === 'bindings') continue
      const row = node('div', null, 'settings-row'); row.dataset.search = field.label.toLowerCase()
      const label = node('label', field.label); label.htmlFor = `setting-${key}`
      const input = node(field.type === 'select' ? 'select' : 'input'); input.id = label.htmlFor
      if (field.type === 'select') for (const option of field.options) { const el = node('option', option); el.value = option; input.append(el) }
      else { input.type = field.type; if (field.type === 'number') { input.min = field.min; input.max = field.max; input.step = field.step } }
      const refresh = () => { if (field.type === 'checkbox') input.checked = draft[key]; else input.value = draft[key] }
      refresh(); controls.set(key, refresh)
      input.addEventListener('input', async () => {
        draft[key] = field.type === 'checkbox' ? input.checked : field.type === 'number' ? input.valueAsNumber : input.value
        if (key === 'desktopNotifications' && input.checked) {
          try {
            if (!globalThis.Notification || await Notification.requestPermission() !== 'granted') throw new Error('Desktop notification permission was not granted.')
          } catch (error) { draft[key] = false; input.checked = false; status.textContent = error.message }
        }
        if (field.category === 'appearance' && input.checkValidity()) applyAppearance(draft)
      })
      row.append(label, input); panels.get(field.category).append(row)
    }
    for (const [engine, label] of [['namd', 'MD / NAMD storage folder'], ['oxdna', 'oxDNA storage folder']]) {
      const row = node('div', null, 'settings-row'); row.append(node('label', label)); row.dataset.search = label.toLowerCase()
      const bar = node('div', null, 'settings-path'); const input = node('input'); input.type = 'text'; input.value = paths[engine]; input.placeholder = 'Workspace default'; input.setAttribute('aria-label', label)
      const result = node('div', '', 'settings-path-status'); result.setAttribute('role', 'status')
      input.addEventListener('input', async () => { paths[engine] = input.value.trim(); result.textContent = 'Not validated' })
      const validate = async () => {
        const path = paths[engine]
        result.textContent = 'Checking…'
        try {
          const checked = await api.getMdRunDirStatus(path || null, engine)
          if (path !== paths[engine]) return
          result.textContent = checked.ok ? `${checked.path} — writable${checked.free_bytes != null ? ` · ${(checked.free_bytes / 2 ** 30).toFixed(1)} GiB free` : ''}` : checked.detail
        } catch (error) { result.textContent = error.message }
      }
      bar.append(input, createButton({ label: 'Browse…', onClick: async () => {
        const chosen = await pickSystemFolder({ api, initialPath: paths[engine], title: label })
        if (chosen) { paths[engine] = chosen; input.value = chosen; void validate() }
      } }), createButton({ label: 'Validate', onClick: validate }))
      row.append(bar, result); panels.get('storage').append(row)
    }
    const addAction = (category, label, action) => panels.get(category).append(createButton({ label, onClick: action }))
    addAction('saving', 'Clear recent-file list…', () => {
      if (window.confirm('Clear recent-file entries in this browser? Saved files and recovery data are kept.')) { clearRecentFiles(); status.textContent = 'Recent-file list cleared.' }
    })
    addAction('layout', 'Reset saved sidebar layout…', () => {
      if (!window.confirm('Reset saved sidebar positions and collapsed sections? Takes effect after reload.')) return
      for (const key of Object.keys(localStorage)) if (/^nadoc\.(leftSidebar|rightSidebar|leftPanel|rightPanel)\./.test(key)) localStorage.removeItem(key)
      status.textContent = 'Saved layout reset. Reload when convenient.'
    })
    const shortcuts = node('details'); shortcuts.append(node('summary', 'Keyboard shortcuts'))
    const shortcutRefresh = []
    for (const shortcut of getShortcutDefinitions()) if (shortcut.description) {
      const row = node('div', null, 'settings-row'), label = node('label', shortcut.description)
      const input = node('input'); input.type = 'text'; input.setAttribute('aria-label', `Shortcut for ${shortcut.description}`)
      const id = shortcutId(shortcut)
      const refresh = () => { input.value = draft.shortcutBindings[id] || ''; input.placeholder = formatShortcut(shortcut) }
      refresh(); shortcutRefresh.push(refresh)
      input.addEventListener('input', () => {
        draft.shortcutBindings = { ...draft.shortcutBindings }
        if (input.value.trim()) draft.shortcutBindings[id] = input.value.trim()
        else delete draft.shortcutBindings[id]
      })
      row.append(label, input); shortcuts.append(row)
    }
    controls.set('shortcutBindings', () => shortcutRefresh.forEach(refresh => refresh()))
    panels.get('navigation').append(shortcuts)
    const diagnostic = () => ({ timestamp: new Date().toISOString(), browser: navigator.userAgent, origin: location.origin, online: navigator.onLine, preferences: readPreferences(), localStorageBytes: Object.keys(localStorage).reduce((sum, key) => sum + 2 * (key.length + (localStorage.getItem(key)?.length || 0)), 0) })
    note('diagnostics', 'Diagnostic reports contain browser information and preferences, but omit designs, recovery contents and server paths.')
    const activity = node('pre')
    panels.get('notifications').append(activity)
    addAction('notifications', 'Show recent application messages', () => { activity.textContent = notificationHistory().map(item => `${item.time} [${item.severity}] ${item.message}`).join('\n') || 'No messages in this session.' })
    addAction('notifications', 'Clear message history', () => { clearNotificationHistory(); activity.textContent = 'Message history cleared.' })
    addAction('diagnostics', 'Clear cached library listing', () => { localStorage.removeItem('nadoc:library-files:v1'); status.textContent = 'Library listing cache cleared. Documents and recovery data are unchanged.' })
    const diagnosticText = node('pre'); panels.get('diagnostics').append(diagnosticText)
    addAction('diagnostics', 'Refresh browser storage usage', async () => {
      try { const estimate = await navigator.storage?.estimate?.(); diagnosticText.textContent = JSON.stringify({ ...diagnostic(), storageEstimate: estimate }, null, 2) } catch (error) { status.textContent = error.message }
    })
    addAction('diagnostics', 'Download diagnostic report', () => download('nadoc-diagnostics.json', JSON.stringify(diagnostic(), null, 2)))
    note('management', 'Preference files exclude machine paths, documents, recovery data and all simulation workflow settings. Import and resets are staged until Apply.')
    addAction('management', 'Export preferences', () => {
      try { download('nadoc-preferences.json', exportPreferences(draft)) } catch (error) { status.textContent = error.message }
    })
    const upload = node('input'); upload.type = 'file'; upload.accept = '.json,application/json'; upload.hidden = true
    upload.addEventListener('change', async () => {
      try { if (!upload.files[0]) return; draft = importPreferences(await upload.files[0].text()); for (const refresh of controls.values()) refresh(); applyAppearance(draft); status.textContent = 'Imported preferences ready to apply.' }
      catch (error) { status.textContent = error.message }
      finally { upload.value = '' }
    }); panels.get('management').append(upload)
    addAction('management', 'Import preferences…', () => upload.click())
    addAction('management', 'Reset all preferences', () => { draft = { ...DEFAULTS }; for (const refresh of controls.values()) refresh(); applyAppearance(draft); status.textContent = 'Defaults ready to apply. Storage paths are unchanged.' })
    search.addEventListener('input', () => {
      const query = search.value.toLowerCase().trim()
      for (const [id, panel] of panels) {
        const matches = panel.textContent.toLowerCase().includes(query)
        tabs.get(id).hidden = !matches
      }
      const first = [...tabs].find(([, tab]) => !tab.hidden)
      if (first) activate(tabs.get(active).hidden ? first[0] : active)
      else for (const panel of panels.values()) panel.hidden = true
      status.textContent = [...tabs.values()].some(tab => !tab.hidden) ? '' : 'No matching settings.'
    })
    const apply = async () => {
      if (busy) return
      const invalid = [...body.querySelectorAll('input')].find(input => !input.checkValidity())
      if (invalid) { activate(invalid.closest('[role=tabpanel]').id.replace('settings-panel-', '')); invalid.reportValidity(); return }
      const next = { ...draft }, nextPaths = { ...paths }
      busy = true; applyButton.disabled = true; status.textContent = 'Applying…'
      try {
        validateShortcutConflicts(next.shortcutBindings, getShortcutDefinitions())
        if (next.desktopNotifications && globalThis.Notification?.permission !== 'granted') throw new Error('Enable desktop notification permission before applying this preference.')
        for (const engine of Object.keys(paths)) if (nextPaths[engine] !== originalPaths[engine]) {
          const checked = await api.getMdRunDirStatus(nextPaths[engine] || null, engine)
          if (!checked.ok) throw new Error(`${engine}: ${checked.detail || 'Folder is unavailable.'}`)
        }
        const changedPaths = Object.fromEntries(Object.entries(nextPaths).filter(([engine, path]) => path !== originalPaths[engine]))
        saved = writePreferences(next, localStorage, changedPaths)
        for (const [engine, path] of Object.entries(changedPaths)) {
          originalPaths[engine] = path
          window.dispatchEvent(new CustomEvent(RUN_DIR_EVENT, { detail: { engine, path: path || null } }))
        }
        status.textContent = 'Settings applied.'
      } catch (error) { status.textContent = error.message }
      finally { busy = false; applyButton.disabled = false }
    }
    const applyButton = createButton({ label: 'Apply', variant: 'primary', onClick: apply })
    modal = createModal({ title: 'Settings', size: 'xl', className: 'nadoc-settings', body, dismissOnBackdrop: false,
      actions: [createButton({ label: 'Reset this tab', onClick: () => { for (const [key, field] of Object.entries(FIELDS)) if (field.category === active) { draft[key] = DEFAULTS[key]; controls.get(key)() }; if (active === 'storage') for (const [engine, input] of pathInputs) { paths[engine] = ''; input.value = '' }; applyAppearance(draft) } }), createButton({ label: 'Cancel', onClick: () => modal.close() }), applyButton],
      onClose: () => { if (busy || document.querySelectorAll('.modal__overlay').length > 1) return false; applyAppearance(readPreferences()); focusBefore?.focus(); modal = null },
    })
    modal.root.setAttribute('aria-label', 'Settings')
    modal.root.addEventListener('keydown', event => {
      event.stopPropagation()
      if (event.key === 'Escape') { event.preventDefault(); modal.close(); return }
      if (event.key !== 'Tab') return
      const focusable = [...modal.root.querySelectorAll('button, input, select, summary, [tabindex="0"]')].filter(el => !el.disabled && !el.closest('[hidden]') && el.tabIndex >= 0)
      const first = focusable[0], last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    })
    activate(active); modal.open(); search.focus()
  }
  menuButton?.addEventListener('click', open)
  return { open, dispose: () => { modal?.close(); menuButton?.removeEventListener('click', open) } }
}
