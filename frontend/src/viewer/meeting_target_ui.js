import { createGuestQR, createMeetingTarget, createMobileTrackingTarget } from './meeting_target.js'

/** Local QR/print rendering for the existing guest invitation. No host mutation. */
export function initMeetingTarget({ parent, document: doc = document, onError = () => {}, now = Date.now }) {
  let share = null, busy = false, renderedURL = ''
  const root = doc.createElement('section'); root.className = 'meeting-target'; root.hidden = true
  root.innerHTML = '<div data-guest-qr></div><p data-join-instructions></p><button type="button" class="btn" data-print-meeting-target>Print meeting target</button><button type="button" class="btn" data-print-mobile-target hidden>Print large tracking QR</button><p class="meeting-target-note">Includes a QR camera-tracking prototype and a reference marker for future headset alignment. Generate a new guest QR when you start a new presentation.</p>'
  parent.querySelector('[data-links]').after(root)
  const qr = root.querySelector('[data-guest-qr]'), button = root.querySelector('button')
  const mobileButton = root.querySelector('[data-print-mobile-target]')
  const active = () => !!share?.url && (!Number.isFinite(share.expiresAt) || share.expiresAt > now())
  function update() { root.hidden = !active(); button.disabled = busy || !active(); mobileButton.disabled = button.disabled; mobileButton.hidden = !share?.qrUrl }
  const print = mobile => {
    if (busy || !active()) { update(); return }
    let popup
    try {
      const svg = mobile ? createMobileTrackingTarget(share) : createMeetingTarget(share)
      popup = doc.defaultView.open('', '_blank')
      if (!popup) throw Error('Allow the print window to open, then try again.')
      popup.opener = null
      const target = popup.document
      target.title = 'NADOC meeting target'
      const style = target.createElement('style')
      style.textContent = '@page { size: auto; margin: 10mm; } body { margin: 0; background: white; color: black; } body > svg { display: block; width: 190mm; height: 250mm; } @media screen { body { padding: 12px; } }'
      target.head.append(style)
      target.body.innerHTML = svg
      popup.focus()
      popup.setTimeout(() => { if (!popup.closed) popup.print() }, 100)
    } catch (error) { popup?.close(); onError(error) }
  }
  button.onclick = () => print(false)
  mobileButton.onclick = () => print(true)
  return {
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
    dispose() { share = null; root.remove() },
  }
}
