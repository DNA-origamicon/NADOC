/**
 * Overhang-binding right-click context menu.
 *
 * Extracted verbatim from main.js's inline `_showBindingCtx`/`_hideBindingCtx`
 * (ISSUE-1 Phase 2a — context-menu primitive migration). Behaviour is preserved;
 * the only change is that positioning / outside-click / Escape dismissal now come
 * from the shared `createContextMenu` primitive instead of bespoke DOM + listeners.
 *
 * The owning `contextmenu` raycast listener stays in main.js (it needs camera /
 * canvas / the binding-lines hit test); this module owns only the menu itself.
 *
 * Items: (header = binding name) · Bind/Unbind · Delete binding (danger).
 */

import { createContextMenu } from './primitives/context_menu.js'

/**
 * @param {object} deps
 * @param {{ getState: () => object }} deps.store
 * @param {object} deps.api          — patchOverhangBinding / deleteOverhangBinding
 * @param {(msg: string, opts?: object) => void} deps.showToast
 * @param {(opts: object) => Promise<boolean>} deps.showConfirm
 * @returns {{ show: (bindingId: any, x: number, y: number) => void, hide: () => void }}
 */
export function initOverhangBindingMenu({ store, api, showToast, showConfirm }) {
  let _menu = null

  function hide() {
    _menu?.close()
    _menu = null
  }

  function show(bindingId, clientX, clientY) {
    hide()
    const design = store.getState().currentDesign
    const binding = design?.overhang_bindings?.find(b => b.id === bindingId)
    if (!binding) return

    _menu = createContextMenu({
      x: clientX,
      y: clientY,
      items: [
        { type: 'header', label: binding.name || 'Binding' },
        { type: 'separator' },
        {
          label: binding.bound ? 'Unbind' : 'Bind',
          onClick: async () => {
            try { await api.patchOverhangBinding(bindingId, { bound: !binding.bound }) }
            catch (err) { showToast(err?.message || String(err), { severity: 'error' }) }
          },
        },
        {
          label: 'Delete binding',
          danger: true,
          onClick: async () => {
            const ok = await showConfirm({
              title: `Delete ${binding.name || 'binding'}`,
              message: 'Delete this overhang binding? The associated cluster pose lock will release.',
              danger: true,
              confirmLabel: 'Delete',
            })
            if (!ok) return
            try { await api.deleteOverhangBinding(bindingId) }
            catch (err) { showToast(err?.message || String(err), { severity: 'error' }) }
          },
        },
      ],
      onClose: () => { _menu = null },
    })
  }

  return { show, hide }
}
