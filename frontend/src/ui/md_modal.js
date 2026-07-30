/**
 * The shared launch-decision modal chrome.
 *
 * Several pre-launch questions need the same thing: a dimmed overlay, a title, some
 * explanatory lines, and a row of buttons whose choice the caller awaits. Gate A (water
 * box too big for the GPU) had this inline; the vacuum pre-stage prompt needs the same
 * shape with a different set of answers, so it lives here once rather than being copied.
 *
 * Escape and a backdrop click always resolve to `dismissValue` — never to an action —
 * because dismissing is not an answer.
 */

/**
 * @param {object} spec
 * @param {string} spec.testid       value for data-testid (so each caller stays addressable)
 * @param {string} spec.title
 * @param {string[]} spec.lines
 * @param {Array<{label: string, value: *, choice: string, primary?: boolean}>} spec.choices
 *        Rendered left→right; `choice` becomes the button's data-choice attribute.
 * @param {*} [spec.dismissValue]    resolved on Escape / backdrop click (default false)
 * @param {object} [spec.dataset]    extra dataset keys set on the overlay
 * @returns {Promise<*>} the chosen `value`
 */
export function openChoiceModal({ testid, title, lines = [], choices = [],
                                  dismissValue = false, dataset = {} }) {
  return new Promise((resolve) => {
    let done = false
    const finish = (v) => { if (done) return; done = true; close(); resolve(v) }

    const overlay = document.createElement('div')
    overlay.setAttribute('data-testid', testid)
    Object.entries(dataset).forEach(([k, v]) => { overlay.dataset[k] = v })
    overlay.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10000;'
      + 'display:flex;align-items:center;justify-content:center'

    const box = document.createElement('div')
    box.style.cssText =
      'background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:18px 20px;'
      + 'max-width:460px;width:90%;color:#c9d1d9;font-size:13px;box-shadow:0 8px 30px rgba(0,0,0,0.5)'
    overlay.appendChild(box)

    const h = document.createElement('div')
    h.textContent = title
    h.style.cssText = 'font-size:15px;font-weight:600;margin-bottom:10px;color:#f0f6fc'
    box.appendChild(h)

    lines.forEach((t) => {
      const p = document.createElement('p')
      p.textContent = t
      p.style.cssText = 'margin:0 0 8px;line-height:1.45;color:#c9d1d9'
      box.appendChild(p)
    })

    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:14px'
    box.appendChild(btnRow)

    function close() { overlay.remove(); document.removeEventListener('keydown', onKey) }
    function onKey(e) { if (e.key === 'Escape') finish(dismissValue) }
    document.addEventListener('keydown', onKey)
    overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(dismissValue) })

    choices.forEach((c) => {
      const b = document.createElement('button')
      b.textContent = c.label
      b.setAttribute('data-choice', c.choice)
      b.style.cssText = c.primary
        ? 'background:#238636;border:1px solid #2ea043;color:#fff;border-radius:4px;'
          + 'padding:5px 12px;cursor:pointer;font-size:12px;font-weight:600'
        : 'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;'
          + 'padding:5px 12px;cursor:pointer;font-size:12px'
      b.addEventListener('click', () => finish(c.value))
      btnRow.appendChild(b)
    })

    document.body.appendChild(overlay)
  })
}
