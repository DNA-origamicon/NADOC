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

const _registry = []

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
 * Return metadata for all registered shortcuts.
 * Useful for building a help overlay or command palette entry list.
 */
export function getShortcuts() {
  return _registry.map(({ key, ctrl, shift, alt, description }) => ({
    key,
    ctrl:        ctrl        ?? null,
    shift:       shift       ?? null,
    alt:         alt         ?? null,
    description: description ?? '',
  }))
}

/**
 * Dispatch a keydown event through the registry.
 * Attach this directly to document.addEventListener('keydown', dispatchKeyEvent).
 */
export async function dispatchKeyEvent(e) {
  const inInput    = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'
  const ctrlOrMeta = e.ctrlKey || e.metaKey

  for (const s of _registry) {
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
    if (s.blockedWhen?.())           continue

    await s.handler(e)
    return
  }
}
