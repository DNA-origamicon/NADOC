/**
 * Sequence-warning modal — shown when an oxDNA relaxation is blocked because the
 * design still has undefined ('N') bases.  oxDNA's DNA2 interaction needs a
 * definite base on every nucleotide (sequence-dependent H-bonding), so a job is
 * refused until sequences are finished.  The backend returns the explanatory 400
 * message; this modal surfaces it as a clear blocking popup instead of a quiet
 * inline status line.
 *
 * Reusable: the NAMD path enforces the same requirement and can reuse this.
 */

/**
 * Pure: does a backend error message describe the undefined-sequence block?
 * Used by callers to decide between the popup (sequence problem) and the inline
 * status line (other failures, e.g. "oxDNA binary not found").
 * @param {string|null|undefined} message
 * @returns {boolean}
 */
export function isUndefinedSequenceError(message) {
  if (!message) return false
  const m = String(message).toLowerCase()
  return m.includes('undefined base') ||
         m.includes('no sequence assigned') ||
         (m.includes('assigning sequences') && m.includes('oxdna'))
}

/**
 * Show a blocking warning popup. Returns the overlay element (for tests / manual
 * removal). Clicking the overlay, the ✕, or "OK" dismisses it.
 * @param {{message?: string, onClose?: () => void}} opts
 */
export function showSequenceWarningModal({ message, onClose } = {}) {
  const overlay = document.createElement('div')
  overlay.className = 'seq-warning-overlay'
  overlay.style.cssText = [
    'position:fixed', 'inset:0', 'z-index:10002',
    'background:rgba(0,0,0,0.65)',
    'display:flex', 'align-items:center', 'justify-content:center',
    'padding:24px', 'box-sizing:border-box',
  ].join(';')

  const box = document.createElement('div')
  box.style.cssText = [
    'background:#1a2530', 'border:1px solid #6b4a00',
    'border-radius:10px', 'padding:0',
    'width:min(520px,100%)',
    'display:flex', 'flex-direction:column',
    'font-family:sans-serif', 'color:#cfd8dc',
    'box-shadow:0 12px 48px rgba(0,0,0,0.7)',
  ].join(';')

  const header = document.createElement('div')
  header.style.cssText = [
    'padding:18px 22px 14px', 'border-bottom:1px solid #263238',
    'display:flex', 'align-items:flex-start', 'gap:12px',
  ].join(';')

  const icon = document.createElement('div')
  icon.textContent = '⚠'
  icon.style.cssText = 'font-size:22px;color:#e0a800;line-height:1;flex-shrink:0'

  const title = document.createElement('div')
  title.textContent = 'Finish assigning sequences'
  title.style.cssText = 'flex:1;font-size:15px;font-weight:700;color:#eceff1;margin-top:1px'

  const btnClose = document.createElement('button')
  btnClose.textContent = '✕'
  btnClose.style.cssText = [
    'background:none', 'border:none', 'color:#78909c',
    'font-size:18px', 'cursor:pointer', 'padding:0 2px',
    'line-height:1', 'flex-shrink:0',
  ].join(';')

  header.append(icon, title, btnClose)

  const bodyText = document.createElement('div')
  bodyText.textContent = message ||
    'This design still has undefined bases. Assign sequences (a scaffold plus ' +
    'all staple sequences) before starting an oxDNA relaxation.'
  bodyText.style.cssText = [
    'padding:16px 22px', 'font-size:13px', 'line-height:1.55', 'color:#b0bec5',
  ].join(';')

  const footer = document.createElement('div')
  footer.style.cssText = [
    'padding:12px 22px', 'border-top:1px solid #263238',
    'display:flex', 'justify-content:flex-end', 'gap:10px',
  ].join(';')

  const btnOk = document.createElement('button')
  btnOk.textContent = 'OK'
  btnOk.style.cssText = [
    'background:#37474f', 'border:1px solid #455a64', 'border-radius:6px',
    'color:#eceff1', 'font-size:13px', 'padding:7px 18px', 'cursor:pointer',
  ].join(';')
  footer.append(btnOk)

  box.append(header, bodyText, footer)
  overlay.append(box)

  function close() {
    overlay.remove()
    try { onClose?.() } catch { /* ignore */ }
  }
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close() })
  btnClose.addEventListener('click', close)
  btnOk.addEventListener('click', close)

  document.body.appendChild(overlay)
  btnOk.focus()
  return overlay
}
