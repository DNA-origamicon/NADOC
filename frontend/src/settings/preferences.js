import { parseShortcut } from './shortcut_bindings.js'

/** Versioned browser preferences. Scientific document/job state never enters this store. */
export const SETTINGS_KEY = 'nadoc:preferences:v1'
export const SETTINGS_EVENT = 'nadoc:preferences-changed'
export const CATEGORIES = [
  ['appearance', 'Appearance & accessibility'], ['storage', 'Files & storage'],
  ['saving', 'Saving & recovery'], ['layout', 'Layout & startup'],
  ['viewport', 'Viewport'], ['navigation', 'Navigation & input'],
  ['editor', 'Editor defaults'], ['notifications', 'Notifications'],
  ['diagnostics', 'Data & diagnostics'], ['management', 'Settings management'],
]
const number = (category, label, value, min, max, step = 1) => ({ category, label, value, min, max, step, type: 'number' })
const toggle = (category, label, value) => ({ category, label, value, type: 'checkbox' })
const select = (category, label, value, options) => ({ category, label, value, options, type: 'select' })
export const FIELDS = {
  textScale: number('appearance', 'Application text size multiplier', 1, .75, 2, .05),
  theme: select('appearance', 'Theme', 'dark', ['dark', 'light', 'system']),
  highContrast: toggle('appearance', 'High contrast', false),
  reducedMotion: toggle('appearance', 'Reduce interface motion', false),
  density: select('appearance', 'Control spacing', 'comfortable', ['comfortable', 'compact']),
  autosave: toggle('saving', 'Automatically save workspace files', true),
  autosaveSeconds: number('saving', 'Save delay after editing (seconds)', 1.5, 1, 300, .5),
  warnUnsaved: toggle('saving', 'Warn before leaving with unsaved changes', true),
  recentLimit: number('saving', 'Recent files to retain', 2, 0, 20),
  rememberLayout: toggle('layout', 'Remember sidebar layout', true),
  leftTab: select('layout', 'Default left sidebar tab (after reload)', 'feature-log', ['feature-log', 'dynamics', 'scene', 'photo', 'plates']),
  rightTab: select('layout', 'Default right sidebar tab (after reload)', 'properties', ['properties', 'visualization', 'clustering', 'overhangs', 'annotations']),
  rememberSections: toggle('layout', 'Remember collapsed sections', true),
  background: { category: 'viewport', label: 'Viewport background', type: 'color', value: '#0d1117' },
  antialias: toggle('viewport', 'Antialiasing (after reload)', true),
  frameLimit: number('viewport', 'Maximum frames per second (0 = unlimited)', 0, 0, 240),
  pauseHidden: toggle('viewport', 'Skip viewport draws while browser tab is hidden', false),
  pixelRatio: number('viewport', 'Maximum rendering pixel density', 2, .5, 3, .5),
  showHelixLabels: toggle('viewport', 'Show helix labels by default', false),
  coloringMode: select('viewport', 'Default molecular coloring', 'strand', ['strand', 'base', 'cluster', 'cpk']),
  shortcutBindings: { category: 'navigation', label: 'Keyboard shortcuts', type: 'bindings', value: {} },
  navigationMode: select('navigation', 'Navigation mode', 'multiscale', ['multiscale', 'turntable', 'trackball']),
  rotateSpeed: number('navigation', 'Orbit sensitivity multiplier', 1, .1, 4, .1),
  panSpeed: number('navigation', 'Pan sensitivity multiplier', 1, .1, 4, .1),
  zoomSpeed: number('navigation', 'Zoom sensitivity multiplier', 1, .1, 4, .1),
  zoomToCursor: toggle('navigation', 'Zoom toward cursor (orbit navigation)', true),
  preview: toggle('editor', 'Construction extrusion preview', true),
  selectScaffold: toggle('editor', 'Select scaffold by default', true),
  selectStaples: toggle('editor', 'Select staples by default', true),
  selectStrands: toggle('editor', 'Select whole strands by default', true),
  selectDomains: toggle('editor', 'Select domains by default', false),
  selectEnds: toggle('editor', 'Select ends by default', false),
  desktopNotifications: toggle('notifications', 'Desktop alerts for success and errors while in background', false),
  notificationSound: toggle('notifications', 'Sound for success and error messages', false),
  toastSeconds: number('notifications', 'Notification display time (seconds)', 2.2, 1, 30, .1),
  logRows: number('diagnostics', 'Sync diagnostic history rows', 150, 25, 1000),
  consoleLogging: toggle('diagnostics', 'Mirror sync diagnostics to browser console', false),
  persistentErrors: toggle('notifications', 'Keep error notifications until dismissed', false),
}
export const DEFAULTS = Object.fromEntries(Object.entries(FIELDS).map(([key, field]) => [key, field.value]))
export function validatePreferences(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Expected a preferences object.')
  const result = {}
  for (const [key, value] of Object.entries(input)) {
    const field = FIELDS[key]
    if (!field) throw new Error(`Unknown preference: ${key}`)
    if (field.type === 'bindings') {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid keyboard shortcuts.')
      for (const [id, chord] of Object.entries(value)) {
        if (id.length > 300 || typeof chord !== 'string') throw new Error('Invalid keyboard shortcut.')
        parseShortcut(chord)
      }
      result[key] = { ...value }; continue
    }
    const valid = field.type === 'checkbox' ? typeof value === 'boolean'
      : field.type === 'number' ? typeof value === 'number' && Number.isFinite(value) && value >= field.min && value <= field.max
      : field.type === 'color' ? typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
      : field.options.includes(value)
    if (!valid) throw new Error(`Invalid value for ${field.label}.`)
    result[key] = value
  }
  return result
}
export function readPreferences(storage = globalThis.localStorage) {
  try {
    const values = { ...DEFAULTS, ...validatePreferences(JSON.parse(storage.getItem(SETTINGS_KEY) || '{}')) }
    const legacyPreview = storage.getItem('NADOC_EXTRUDE_PREVIEW')
    if (legacyPreview !== null) values.preview = legacyPreview !== 'false'
    return values
  }
  catch { return { ...DEFAULTS } }
}
export function preference(key) { return readPreferences()[key] }
export function writePreferences(values, storage = globalThis.localStorage, directoryUpdates = {}) {
  const next = { ...DEFAULTS, ...validatePreferences(values) }
  const updates = { [SETTINGS_KEY]: JSON.stringify(next), NADOC_EXTRUDE_PREVIEW: String(next.preview) }
  for (const [engine, path] of Object.entries(directoryUpdates)) {
    if (!['namd', 'oxdna'].includes(engine) || typeof path !== 'string') throw new Error('Invalid storage preference.')
    updates[`nadoc.runDir.${engine}`] = path
  }
  const before = Object.fromEntries(Object.keys(updates).map(key => [key, storage.getItem(key)]))
  try { for (const [key, value] of Object.entries(updates)) storage.setItem(key, value) }
  catch (error) {
    for (const [key, value] of Object.entries(before)) {
      try { if (value === null) storage.removeItem(key); else storage.setItem(key, value) } catch { /* Preserve the original persistence failure. */ }
    }
    throw new Error(`Could not save preferences: ${error.message}`)
  }
  globalThis.window?.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: next }))
  return next
}
export function importPreferences(text) {
  const data = JSON.parse(text)
  if (data?.format !== 'nadoc-preferences' || data.version !== 1) throw new Error('Unsupported preferences file.')
  return { ...DEFAULTS, ...validatePreferences(data.preferences) }
}
export function exportPreferences(values) {
  return JSON.stringify({ format: 'nadoc-preferences', version: 1, preferences: validatePreferences(values) }, null, 2)
}
