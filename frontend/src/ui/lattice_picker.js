/**
 * Lattice-type picker — a small modal shown on "New Part" before the design is
 * created, letting the user choose Honeycomb (default) or Square lattice.
 *
 * Self-contained: builds its own overlay DOM, owns no app state, captures
 * nothing from the caller. Returns a Promise that resolves to the chosen
 * lattice string ('HONEYCOMB' | 'SQUARE') or null if cancelled (Cancel button
 * or Escape). Enter accepts the current selection.
 *
 * Extracted verbatim from main.js's `_pickLattice` closure helper.
 *
 * @returns {Promise<'HONEYCOMB'|'SQUARE'|null>}
 */
export function pickLattice() {
  return new Promise(resolve => {
    const overlay = document.createElement('div')
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9100;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center'
    const box = document.createElement('div')
    box.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;width:280px;padding:20px;font-family:var(--font-ui);display:flex;flex-direction:column;gap:14px'
    box.tabIndex = -1

    const titleEl = document.createElement('div')
    titleEl.textContent = 'Lattice type'
    titleEl.style.cssText = 'color:#c9d1d9;font-size:13px;font-weight:500'

    const optsEl = document.createElement('div')
    optsEl.style.cssText = 'display:flex;flex-direction:column;gap:8px'

    let selected = 'HONEYCOMB'
    const labels = []
    for (const [val, name, desc] of [['HONEYCOMB', 'Honeycomb', 'Standard — 10.5 bp/turn avg'], ['SQUARE', 'Square', 'Square lattice — 10 bp/turn avg']]) {
      const lbl = document.createElement('label')
      lbl.style.cssText = 'display:flex;align-items:flex-start;gap:10px;cursor:pointer;padding:8px 10px;border-radius:5px;border:1px solid ' + (val === 'HONEYCOMB' ? '#388bfd' : '#21262d')
      const radio = document.createElement('input')
      radio.type = 'radio'; radio.name = 'pick-lattice'; radio.value = val; radio.checked = val === 'HONEYCOMB'
      radio.style.marginTop = '2px'
      radio.addEventListener('change', () => {
        selected = val
        labels.forEach((l, i) => { l.style.borderColor = [val === 'HONEYCOMB' ? '#388bfd' : '#21262d', val === 'SQUARE' ? '#388bfd' : '#21262d'][i] })
      })
      const text = document.createElement('div')
      const n = document.createElement('div'); n.textContent = name; n.style.cssText = 'color:#c9d1d9;font-size:12px'
      const d = document.createElement('div'); d.textContent = desc; d.style.cssText = 'color:#484f58;font-size:var(--text-xs);margin-top:2px'
      text.append(n, d); lbl.append(radio, text); optsEl.appendChild(lbl); labels.push(lbl)
    }

    const btnsEl = document.createElement('div')
    btnsEl.style.cssText = 'display:flex;justify-content:flex-end;gap:8px'
    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'; cancelBtn.style.cssText = 'padding:5px 14px;background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;cursor:pointer;font-family:var(--font-ui);font-size:12px'
    const createBtn = document.createElement('button')
    createBtn.textContent = 'Create'; createBtn.style.cssText = 'padding:5px 14px;background:#1f6feb;border:none;color:#fff;border-radius:4px;cursor:pointer;font-family:var(--font-ui);font-size:12px'
    const done = (v) => { document.body.removeChild(overlay); resolve(v) }
    cancelBtn.addEventListener('click', () => done(null))
    createBtn.addEventListener('click', () => done(selected))
    box.addEventListener('keydown', e => { if (e.key === 'Escape') done(null); if (e.key === 'Enter') done(selected) })
    btnsEl.append(cancelBtn, createBtn)
    box.append(titleEl, optsEl, btnsEl)
    overlay.appendChild(box)
    document.body.appendChild(overlay)
    setTimeout(() => { box.focus() }, 30)
  })
}
