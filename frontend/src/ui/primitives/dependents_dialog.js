/**
 * showDependentsDecision — three-way modal for deleting a feature whose later
 * entries depend on it.
 *
 * The backend's `DELETE /design/features/{i}` returns `needs_cascade_decision`
 * (without mutating) when removing entry K would orphan later entries that were
 * built on its geometry or baked on top of it (non-replayable auto-ops). This
 * dialog lists those dependents and lets the user choose:
 *
 *   'cascade' — delete K AND all listed dependents
 *   'revert'  — roll the design back to before K (drops K + everything after)
 *   null      — cancel, no change
 *
 * @param {object} opts
 * @param {string} opts.targetLabel               — label of the feature being deleted
 * @param {{index:number,label:string}[]} opts.dependents
 * @returns {Promise<'cascade'|'revert'|null>}
 */
import { createModal } from './modal.js'
import { createButton } from './button.js'
import { el } from './dom.js'

export function showDependentsDecision({ targetLabel = 'this feature', dependents = [] } = {}) {
  return new Promise((resolve) => {
    let resolved = false
    const _resolve = (v) => { if (!resolved) { resolved = true; resolve(v) } }

    const list = el('ul', {
      attrs: { style: 'margin:8px 0 0;padding-left:18px;max-height:180px;overflow:auto' },
    })
    for (const d of dependents) {
      list.append(el('li', {
        attrs: { style: 'font-size:var(--text-sm);line-height:var(--leading-normal);color:#c9d1d9' },
        text: `F${d.index + 1}: ${d.label}`,
      }))
    }

    const body = el('div', {
      attrs: { style: 'font-size:var(--text-md);line-height:var(--leading-normal)' },
    })
    const n = dependents.length
    body.append(el('div', {
      text: `${n} later feature${n === 1 ? '' : 's'} depend on "${targetLabel}" and can't be `
          + `kept without it:`,
    }))
    body.append(list)
    body.append(el('div', {
      attrs: { style: 'margin-top:10px;color:#8b949e;font-size:var(--text-sm)' },
      text: 'Delete them together, or revert the design to before this feature.',
    }))

    const cancelBtn = createButton({
      label: 'Cancel', variant: 'default',
      onClick: () => { _resolve(null); modal.close() },
    })
    const revertBtn = createButton({
      label: 'Revert to here', variant: 'default',
      onClick: () => { _resolve('revert'); modal.close() },
    })
    const cascadeBtn = createButton({
      label: `Delete all (${n + 1})`, variant: 'danger',
      onClick: () => { _resolve('cascade'); modal.close() },
    })

    const modal = createModal({
      title: 'Delete dependent features?',
      size: 'sm',
      body,
      actions: [cancelBtn, revertBtn, cascadeBtn],
      onClose: () => _resolve(null),
    })
  })
}
