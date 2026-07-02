/**
 * showChoice — Promise-returning multi-option modal (like showConfirm but with
 * N labelled choices). Resolves to the chosen option's `value`, or `null` on
 * cancel (Escape / backdrop / × / Cancel).
 *
 * Usage:
 *   const pick = await showChoice({
 *     title: 'Generate overhang sequence',
 *     message: 'Both overhangs already have a sequence. What would you like to do?',
 *     options: [
 *       { value: 'pair',     label: 'New pair (regenerate both)' },
 *       { value: 'override', label: 'New sequence (this overhang only)' },
 *       { value: 'rc',       label: 'Reverse complement of the partner' },
 *     ],
 *   })
 *   if (pick === 'pair') { ... }
 *
 * The option buttons stack full-width in the body (readable for descriptive
 * labels); Cancel sits in the footer.
 *
 * @param {object} opts
 * @param {string} [opts.title='Choose']
 * @param {string|HTMLElement} [opts.message='']
 * @param {{value:string,label:string,tooltip?:string,variant?:string}[]} opts.options
 * @param {string} [opts.cancelLabel='Cancel']
 * @returns {Promise<string|null>}
 */
import { createModal } from './modal.js'
import { createButton } from './button.js'
import { el } from './dom.js'

export function showChoice(opts = {}) {
  const { title = 'Choose', message = '', options = [], cancelLabel = 'Cancel' } = opts

  return new Promise((resolve) => {
    let resolved = false
    const _resolve = (v) => { if (!resolved) { resolved = true; resolve(v) } }

    const container = el('div', { attrs: { style: 'display:flex;flex-direction:column;gap:8px' } })
    if (message) {
      container.appendChild(el('div', {
        attrs: { style: 'font-size:var(--text-md);line-height:var(--leading-normal);margin-bottom:4px' },
        text: (message instanceof HTMLElement) ? undefined : String(message),
      }))
      if (message instanceof HTMLElement) container.lastChild.appendChild(message)
    }

    const optBtns = options.map((o) => {
      const b = createButton({
        label: o.label,
        variant: o.variant ?? 'primary',
        title: o.tooltip,   // longer description on hover
        onClick: () => { _resolve(o.value); modal.close() },
      })
      b.style.width = '100%'
      container.appendChild(b)
      return b
    })

    const cancelBtn = createButton({
      label: cancelLabel,
      variant: 'default',
      onClick: () => { _resolve(null); modal.close() },
    })

    const modal = createModal({
      title,
      size: 'sm',
      body: container,
      actions: [cancelBtn],
      onClose: () => { _resolve(null) },
    })
    modal.open()
    setTimeout(() => optBtns[0]?.focus(), 0)
  })
}
