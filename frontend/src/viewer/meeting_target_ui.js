import { createGuestQR, createGuestInvitationPrint } from './meeting_target.js'

/** Local QR/print rendering for the existing guest invitation. No host mutation. */
export function initMeetingTarget({ parent, document: doc = document, onError = () => {}, now = Date.now }) {
  let share = null, busy = false, renderedURL = ''
  const root = doc.createElement('section'); root.className = 'meeting-target'; root.hidden = true
  root.innerHTML = '<div data-guest-qr></div><p data-join-instructions></p><button type="button" class="btn" data-print-meeting-target>Print guest invitation</button><p class="meeting-target-note">The design’s QR is reusable. Reset the link to revoke old invitations.</p>'
  parent.querySelector('[data-links]').after(root)
  const qr = root.querySelector('[data-guest-qr]'), button = root.querySelector('button')
  const qrDialog = doc.createElement('dialog')
  qrDialog.id = 'presentation-qr-dialog'
  qrDialog.className = 'sharing-dialog'
  qrDialog.setAttribute('aria-labelledby', 'presentation-qr-title')
  qrDialog.innerHTML = '<header class="sharing-header"><h2 id="presentation-qr-title">Passwordless link QR code</h2><button type="button" class="btn" data-close aria-label="Close">×</button></header><div class="meeting-target meeting-target--presentation"><div data-guest-qr></div><p>Scan to join with your guest name. Anyone with this QR can join without a password.</p><p data-qr-unavailable hidden>Open a design to prepare its passwordless invitation.</p></div>'
  qrDialog.querySelector('[data-close]').onclick = () => qrDialog.close()
  doc.body.append(qrDialog)
  const presentationQR = qrDialog.querySelector('[data-guest-qr]')
  const active = () => !!share?.url && (!Number.isFinite(share.expiresAt) || share.expiresAt > now())
  function update() {
    root.hidden = !active(); button.disabled = busy || !active()
    const available = active() && !!share?.qrUrl
    const svg = available ? qr.innerHTML : ''
    if (presentationQR.innerHTML !== svg) presentationQR.innerHTML = svg
    qrDialog.querySelector('[data-qr-unavailable]').hidden = available
    qrDialog.querySelector('.meeting-target > p').hidden = !available
  }
  const print = () => {
    if (busy || !active()) { update(); return }
    let popup
    try {
      const svg = createGuestInvitationPrint(share)
      popup = doc.defaultView.open('', '_blank')
      if (!popup) throw Error('Allow the print window to open, then try again.')
      popup.opener = null
      const target = popup.document
      target.title = 'NADOC guest invitation'
      const style = target.createElement('style')
      style.textContent = '@page { size: auto; margin: 10mm; } body { margin: 0; background: white; color: black; } body > svg { display: block; width: 190mm; height: 250mm; } @media screen { body { padding: 12px; } }'
      target.head.append(style)
      target.body.innerHTML = svg
      popup.focus()
      popup.setTimeout(() => { if (!popup.closed) popup.print() }, 100)
    } catch (error) { popup?.close(); onError(error) }
  }
  button.onclick = () => print()
  return {
    showQR() {
      update()
      if (!busy && active() && share?.qrUrl && !qrDialog.open) qrDialog.showModal()
    },
    setShare(value) {
      share = value ? { ...value, url: value.qrUrl || value.url } : null
      const next = share?.url ?? ''
      if (next !== renderedURL) {
        try { qr.innerHTML = next ? createGuestQR(next) : ''; renderedURL = next }
        catch (error) { qr.replaceChildren(); share = null; onError(error) }
      }
      root.querySelector("[data-join-instructions]").textContent = value?.qrUrl ? "Scan to join with your guest name. Anyone with this QR can join." : "Scan to join, then enter the meeting password."
      update()
    },
    setBusy(value) { busy = value; update() },
    dispose() { share = null; root.remove(); qrDialog.remove() },
  }
}
