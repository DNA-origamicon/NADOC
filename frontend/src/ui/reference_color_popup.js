import { createModal } from './primitives/modal.js'

/** Live appearance editor; closing without Done restores the opening values. */
export function openReferenceColorPopup({ color, opacity, onChange, onClose }) {
  const body = document.createElement('div')
  body.style.cssText = 'display:grid;gap:16px'
  body.innerHTML = `
    <label style="display:grid;gap:6px">Color
      <input type="color" aria-label="Reference color" style="width:100%;height:64px;cursor:pointer">
    </label>
    <label style="display:grid;gap:6px">Hex color
      <input type="text" aria-label="Hex color" maxlength="7" spellcheck="false" placeholder="#RRGGBB">
    </label>
    <label style="display:grid;gap:6px">Transparency <output></output>
      <input type="range" aria-label="Transparency" min="0" max="100" step="1">
    </label>`
  const picker = body.querySelector('[type=color]')
  const hex = body.querySelector('[type=text]')
  const transparency = body.querySelector('[type=range]')
  const output = body.querySelector('output')
  picker.value = hex.value = color
  transparency.value = Math.round((1 - opacity) * 100)
  function preview() {
    output.value = `${transparency.value}%`
    onChange({ color: picker.value, opacity: 1 - Number(transparency.value) / 100 })
  }
  output.value = `${transparency.value}%`
  picker.addEventListener('input', () => { hex.value = picker.value; hex.setCustomValidity(''); preview() })
  hex.addEventListener('input', () => {
    const value = hex.value.trim()
    const valid = /^#?[0-9a-f]{6}$/i.test(value)
    hex.setCustomValidity(valid ? '' : 'Enter a six-digit hex color, such as #8da9c4.')
    if (valid) { picker.value = '#' + value.replace(/^#/, ''); preview() }
  })
  transparency.addEventListener('input', preview)
  let accepted = false
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel'
  const done = document.createElement('button'); done.type = 'button'; done.textContent = 'Done'
  const popup = createModal({ title: 'Reference color', size: 'sm', body, actions: [cancel, done],
    onClose() { if (!accepted) onChange({ color, opacity }); onClose?.() },
  })
  cancel.addEventListener('click', () => popup.close())
  done.addEventListener('click', () => { if (!hex.reportValidity()) return; accepted = true; popup.close() })
  popup.open()
  picker.focus()
  return popup
}
