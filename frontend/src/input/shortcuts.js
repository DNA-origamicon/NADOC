/**
 * Global keyboard shortcut registry.
 *
 * Replaces the monolithic document.addEventListener('keydown', ...) in main.js
 * with a structured dispatch table.  Each shortcut is registered via
 * registerShortcut() and dispatched through dispatchKeyEvent().
 *
 * Key matching is case-insensitive (e.key.toLowerCase()).
 * Modifier flags are tri-state: true = required, false = must be absent,
 * undefined = ignored.  `ctrl: true` matches both Ctrl and Meta/Cmd.
 *
 * Usage:
 *   import { registerShortcut, dispatchKeyEvent } from './input/shortcuts.js'
 *
 *   registerShortcut({
 *     key: 'z', ctrl: true, shift: false,
 *     description: 'Undo',
 *     blockedWhen: () => isDeformActive(),
 *     handler: async (e) => { e.preventDefault(); await api.undo() },
 *   })
 *
 *   document.addEventListener('keydown', dispatchKeyEvent)
 */

import { preference } from '../settings/preferences.js'
import { parseShortcut, shortcutId } from '../settings/shortcut_bindings.js'

const _registry = []

export function isEditableTarget(target) {
  if (!target || typeof target !== 'object') return false
  const tag = target.tagName?.toUpperCase()
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
    || target.isContentEditable === true
    || target.closest?.('[contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"]') != null
}

function hasOpenPopup(doc) {
  return [...(doc?.querySelectorAll('.modal__overlay, .modal-overlay, [role="dialog"], dialog[open], [popover]') || [])].some(popup => {
    if (popup.hasAttribute('popover') && !popup.matches(':popover-open')) return false
    for (let node = popup; node; node = node.parentElement) {
      const style = doc.defaultView?.getComputedStyle(node)
      if (node.hidden || node.getAttribute('aria-hidden') === 'true'
          || style?.display === 'none' || style?.visibility === 'hidden') return false
    }
    return true
  })
}

/**
 * Register a keyboard shortcut.
 *
 * @param {Object}   spec
 * @param {string}   spec.key              - Matched case-insensitively against event.key
 * @param {boolean}  [spec.ctrl]           - true=required, false=must be absent, undefined=ignored
 * @param {boolean}  [spec.shift]          - true=required, false=must be absent, undefined=ignored
 * @param {boolean}  [spec.alt]            - true=required, false=must be absent, undefined=ignored
 * @param {boolean}  [spec.blockedInInput] - Skip when cursor is in an INPUT or TEXTAREA
 * @param {boolean}  [spec.noRepeat]       - Skip auto-repeated keydown events (key held down).
 *                                           Should be true for all toggle actions.
 * @param {Function} [spec.blockedWhen]    - () => boolean, additional runtime block condition
 * @param {string}   [spec.description]    - Human-readable label for command palette / help
 * @param {Function} spec.handler          - async (event) => void
 */
export function registerShortcut(spec) {
  _registry.push(spec)
}

/**
 * Clear the registry. Intended for test isolation (the registry is a
 * module-level singleton, so factory tests must reset it between cases).
 */
export function clearShortcuts() {
  _registry.length = 0
}

/**
 * Return metadata for all registered shortcuts.
 * Useful for building a help overlay or command palette entry list.
 */
export function getShortcutDefinitions() {
  return _registry.map(({ key, ctrl, shift, alt, description }) => ({
    key,
    ctrl:        ctrl        ?? null,
    shift:       shift       ?? null,
    alt:         alt         ?? null,
    description: description ?? '',
  }))
}

/** Shortcut help reflects the currently configured bindings. */
export function getShortcuts() {
  const bindings = preference('shortcutBindings')
  return getShortcutDefinitions().map(spec => {
    const chord = bindings[shortcutId(spec)]
    return chord ? { ...spec, ...parseShortcut(chord) } : spec
  })
}

/**
 * Dispatch a keydown event through the registry.
 * Attach this directly to document.addEventListener('keydown', dispatchKeyEvent).
 */
export async function dispatchKeyEvent(e) {
  const doc = e.target?.ownerDocument || globalThis.document
  const inInput    = isEditableTarget(e.target) || isEditableTarget(doc?.activeElement)
  const ctrlOrMeta = e.ctrlKey || e.metaKey
  // Number commands belong to the workspace, never to a dialog or text entry.
  // This is a registry invariant, including registrations without blockedInInput.
  if (/^[0-9]$/.test(e.key) && (inInput || hasOpenPopup(doc))) return

  const bindings = preference('shortcutBindings')
  for (const original of _registry) {
    const chord = bindings[shortcutId(original)]
    const s = chord ? { ...original, ...parseShortcut(chord) } : original
    // Key match (case-insensitive)
    if (e.key.toLowerCase() !== s.key.toLowerCase()) continue

    // Modifier checks — undefined means "don't care"
    if (s.ctrl  === true  && !ctrlOrMeta)  continue
    if (s.ctrl  === false && ctrlOrMeta)   continue
    if (s.shift === true  && !e.shiftKey)  continue
    if (s.shift === false && e.shiftKey)   continue
    if (s.alt   === true  && !e.altKey)    continue
    if (s.alt   === false && e.altKey)     continue

    // Key-repeat guard
    if (s.noRepeat && e.repeat) continue

    // Runtime block conditions
    if (s.blockedInInput && inInput) continue
    if (s.canvasOnly && !['CANVAS', 'BODY'].includes(e.target?.tagName?.toUpperCase())) continue
    if (s.blockedWhen?.())           continue

    await s.handler(e)
    return
  }
}
