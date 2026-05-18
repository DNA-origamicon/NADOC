/**
 * showConfirm — Promise-returning confirmation modal.
 *
 * Replaces `window.confirm(...)` for destructive prompts so they match the
 * dark theme, can be focus-trapped, and respect Escape/click-outside the
 * same way other modals do.
 *
 * Usage:
 *   const ok = await showConfirm({
 *     title: 'Delete strand',
 *     message: 'Strand "s_h0_0_0" will be removed. This cannot be undone via Undo.',
 *     danger: true,
 *     confirmLabel: 'Delete',
 *   })
 *   if (ok) await api.deleteStrand(...)
 *
 * The returned Promise resolves to `true` if the user confirms, `false` if
 * they cancel (Escape, backdrop click, ×, or Cancel button).
 *
 * @param {object} opts
 * @param {string} [opts.title='Confirm']
 * @param {string|HTMLElement} opts.message    — body text (string) or DOM
 * @param {boolean} [opts.danger=false]        — primary button styled as destructive
 * @param {string} [opts.confirmLabel='Confirm']
 * @param {string} [opts.cancelLabel='Cancel']
 * @returns {Promise<boolean>}
 */

import { createModal } from './modal.js'
import { createButton } from './button.js'
import { el } from './dom.js'

export function showConfirm(opts = {}) {
  const {
    title = 'Confirm',
    message = '',
    danger = false,
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
  } = opts

  return new Promise((resolve) => {
    let resolved = false
    function _resolve(value) {
      if (resolved) return
      resolved = true
      resolve(value)
    }

    const body = (message instanceof HTMLElement)
      ? message
      : el('div', {
          attrs: { style: 'font-size:var(--text-md);line-height:var(--leading-normal);white-space:pre-wrap' },
          text: String(message),
        })

    const cancelBtn = createButton({
      label: cancelLabel,
      variant: 'default',
      onClick: () => { _resolve(false); modal.close() },
    })
    const confirmBtn = createButton({
      label: confirmLabel,
      variant: danger ? 'danger' : 'primary',
      onClick: () => { _resolve(true); modal.close() },
    })

    const modal = createModal({
      title,
      size: 'sm',
      body,
      actions: [cancelBtn, confirmBtn],
      onClose: () => { _resolve(false) },  // close via X / Escape / backdrop = cancel
    })
    modal.open()

    // Focus the confirm button so Enter commits and Escape (handled by modal)
    // cancels. For dangerous prompts, focus Cancel instead to avoid Enter-fat-fingering.
    setTimeout(() => (danger ? cancelBtn : confirmBtn).focus(), 0)
  })
}
