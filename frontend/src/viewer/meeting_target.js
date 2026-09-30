import qrcode from 'qrcode-generator'

// Official AprilRobotics tag36h11/tag36_11_00000.png, including one white cell
// around the 8×8 black-border extent. 1 means black. Do not rotate/re-encode.
const TAG_ROWS = ['0000000000', '0111111110', '0100101010', '0110001010', '0110011110', '0101011110', '0110100110', '0111101110', '0111111110', '0000000000']
export const ROOM_MARKER = Object.freeze({ family: 'tag36h11', id: 0, sizeMeters: .15 })
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
/** Physical-size SVG fits A4 and US Letter at actual size; no remote resources. */
export function createMeetingTarget({ url }) {
  const { n, markup } = qrMarkup(url)
  return `<svg xmlns="${XMLNS}" width="190mm" height="250mm" viewBox="0 0 190 250">
<title>NADOC meeting target</title><rect width="190" height="250" fill="white"/>
<g font-family="sans-serif" fill="black"><text x="95" y="7" text-anchor="middle" font-size="4">NADOC room reference · THIS WAY UP ↑</text>
<svg data-room-marker="tag36h11:0" x="1.25" y="15" width="187.5" height="187.5" viewBox="0 0 10 10" shape-rendering="crispEdges"><rect width="10" height="10" fill="white"/><path d="${cells(TAG_ROWS)}"/></svg>
<svg x="5" y="207" width="40" height="40" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges">${markup}</svg>
<text x="55" y="212" font-size="4">Scan to join this presentation</text>
<text x="55" y="219" font-size="2.9">${new URLSearchParams(new URL(url).hash.slice(1)).get("entry") === "qr" ? "Scan and enter your guest name. No password." : "Ask the presenter for the meeting password."}</text>
<text x="55" y="226" font-size="2.8">The guest link expires with this presentation.</text>
<text x="55" y="233" font-size="2.8">Print at 100% / actual size. Check the ruler:</text>
<path d="M55 239h100M55 237v4M155 237v4" stroke="black" stroke-width=".3"/>
<text x="105" y="246" text-anchor="middle" font-size="2.8">100 mm · Marker black border: 150 mm</text></g>
</svg>`
}

/** Larger, QR-only sheet for the mobile tracking prototype. */
export function createMobileTrackingTarget({ url }) {
  const link = new URL(guestURL(url)), params = new URLSearchParams(link.hash.slice(1))
  params.set('qrmm', '150'); link.hash = params.toString()
  const { n, markup } = qrMarkup(link.href)
  return `<svg xmlns="${XMLNS}" width="190mm" height="250mm" viewBox="0 0 190 250"><title>NADOC mobile tracking target</title><rect width="190" height="250" fill="white"/><g font-family="sans-serif" fill="black"><text x="95" y="15" text-anchor="middle" font-size="5">Scan to join · enter your guest name</text><svg data-mobile-marker="qr" x="20" y="30" width="150" height="150" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges">${markup}</svg><text x="95" y="195" text-anchor="middle" font-size="4">Phone tracking: keep the entire QR visible.</text><text x="95" y="207" text-anchor="middle" font-size="3.5">Print at 100% / actual size · QR including white border: 150 mm</text><path d="M45 223h100M45 221v4M145 221v4" stroke="black" stroke-width=".3"/><text x="95" y="233" text-anchor="middle" font-size="3.5">Check this ruler measures 100 mm.</text><text x="95" y="244" text-anchor="middle" font-size="3">Anyone with this QR can join when the presenter starts.</text></g></svg>`
}
