import qrcode from 'qrcode-generator'

const XMLNS = 'http://www.w3.org/2000/svg'
function cells(rows) {
  return rows.flatMap((row, y) => Array.from(row, (v, x) => v === '1' ? `M${x},${y}h1v1h-1z` : '')).join('')
}
function guestURL(value) {
  if (typeof value !== 'string' || !value || value.length > 2048) throw Error('A guest invitation link is required.')
  const url = new URL(value)
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || new URLSearchParams(url.hash.slice(1)).get('role') === 'presenter') throw Error('Use the guest invitation link for this target.')
  return url.href
}
function qrMarkup(value) {
  const qr = qrcode(0, 'M'); qr.addData(guestURL(value)); qr.make()
  const n = qr.getModuleCount(), rows = Array.from({ length: n }, (_, y) => Array.from({ length: n }, (_, x) => qr.isDark(y, x) ? '1' : '0').join(''))
  return { n: n + 8, markup: `<rect width="100%" height="100%" fill="white"/><path transform="translate(4 4)" fill="black" d="${cells(rows)}"/>` }
}
export function createGuestQR(url) {
  const { n, markup } = qrMarkup(url)
  return `<svg xmlns="${XMLNS}" viewBox="0 0 ${n} ${n}" role="img" aria-label="Scan to join the presentation" shape-rendering="crispEdges">${markup}</svg>`
}
/** Printable guest invitation, without spatial tracking metadata. */
export function createGuestInvitationPrint({ url }) {
  const { n, markup } = qrMarkup(url)
  return `<svg xmlns="${XMLNS}" width="190mm" height="250mm" viewBox="0 0 190 250"><title>NADOC guest invitation</title><rect width="190" height="250" fill="white"/><g font-family="sans-serif" fill="black"><text x="95" y="15" text-anchor="middle" font-size="6" font-weight="700">Scan to view molecular CAD demo</text><svg data-guest-invitation="qr" x="20" y="30" width="150" height="150" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges">${markup}</svg><text x="95" y="200" text-anchor="middle" font-size="4">Enter your guest name to join.</text><text x="95" y="215" text-anchor="middle" font-size="3">Ask the presenter for a password if prompted.</text></g></svg>`
}
