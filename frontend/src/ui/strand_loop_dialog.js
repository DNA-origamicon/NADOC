import './strand_loop_dialog.css'

/** Shared strand-loop editor for the 3D and cadnano hosts. */
export function loopAt(strand, anchor) {
  return strand?.loops?.find(loop => loop.helix_id === anchor.helix_id &&
    loop.bp_index === anchor.bp_index && loop.direction === anchor.direction)
}

export function openStrandLoopDialog({ strand, anchor, save, getError = () => null }) {
  document.getElementById('strand-loop-dialog')?.remove()
  const existing = loopAt(strand, anchor)
  const dialog = document.createElement('dialog')
  dialog.id = 'strand-loop-dialog'
  dialog.className = 'modal modal--md strand-loop-dialog'
  dialog.setAttribute('aria-labelledby', 'strand-loop-title')
  dialog.innerHTML = `<form>
    <header class="modal__header"><h3 class="modal__title" id="strand-loop-title">${existing ? 'Edit loop' : 'Add loop here'}</h3></header>
    <div class="modal__body strand-loop-dialog__body">
      <p>Insert unpaired bases after this nucleotide in the strand’s 5′→3′ direction.</p>
      <label class="strand-loop-dialog__field"><span>Extra nucleotides</span><input class="input" name="length" type="number" min="1" max="512" step="1" required></label>
      <label class="strand-loop-dialog__field"><span>Aspect ratio <small>Along helix / outward</small></span><input class="input" name="aspect" type="number" min="1" max="10" step="0.1" required></label>
      <label class="strand-loop-dialog__field"><span>Rotation around helix (°)</span><input class="input" name="rotation" type="number" min="-180" max="180" step="1" required></label>
      <p class="strand-loop-dialog__hint">${strand.strand_type === 'scaffold' ? 'Assign the scaffold sequence to fill this loop.' : 'New loop bases start as N. Use Edit sequence to change them.'}</p>
      <p class="strand-loop-dialog__error" role="alert"></p>
    </div>
    <footer class="modal__actions">
      ${existing ? '<button class="btn btn--danger" type="button" data-action="remove">Remove loop</button>' : ''}
      <button class="btn" type="button" data-action="cancel">Cancel</button>
      <button class="btn btn--primary" type="submit">${existing ? 'Save' : 'Add loop'}</button>
    </footer></form>`
  const form = dialog.querySelector('form')
  form.elements.namedItem('length').value = existing?.length ?? 30
  form.elements.namedItem('aspect').value = existing?.aspect_ratio ?? 3
  form.elements.namedItem('rotation').value = existing?.rotation_deg ?? 0
  const close = () => dialog.remove()
  dialog.querySelector('[data-action="cancel"]').onclick = close
  dialog.addEventListener('cancel', close)
  async function submit(length) {
    const buttons = [...dialog.querySelectorAll('button')]
    buttons.forEach(button => { button.disabled = true })
    try {
      const result = await save({ strand_id: strand.id, helix_id: anchor.helix_id,
        bp_index: anchor.bp_index, direction: anchor.direction, length,
        aspect_ratio: Number(form.elements.namedItem('aspect').value),
        rotation_deg: Number(form.elements.namedItem('rotation').value) })
      if (!result) throw new Error(getError() || 'The loop could not be saved.')
      close()
    } catch (error) {
      dialog.querySelector('[role="alert"]').textContent = error.message
      buttons.forEach(button => { button.disabled = false })
    }
  }
  form.onsubmit = event => { event.preventDefault(); if (form.reportValidity()) void submit(Number(form.elements.namedItem('length').value)) }
  dialog.querySelector('[data-action="remove"]')?.addEventListener('click', () => { void submit(0) })
  document.body.appendChild(dialog)
  dialog.showModal()
  form.elements.namedItem('length').focus()
  return dialog
}
