/**
 * Hex colour normalisation for `<input type="color">`.
 *
 * The native colour input's value setter is unforgiving: anything that isn't
 * exactly 7-character lowercase `#rrggbb` is silently replaced with `#000000`.
 * So `input.value = someColorFromTheModel` turns a shorthand, an uppercase hex or
 * an unset value into black without a word of warning — every picker in the app
 * has to launder its value through something like this first.
 *
 * NOTE: `ui/spreadsheet.js` and `cadnano-editor/pathview/strands_spreadsheet.js`
 * each carry a private copy of this. Folding them in is a separate change — the
 * blast radius there is unrelated to whatever brought you here.
 */

const FULL  = /^#[0-9a-fA-F]{6}$/
const SHORT = /^#[0-9a-fA-F]{3}$/

/**
 * @param {string|number|null|undefined} c  '#rrggbb', '#rgb', 'rrggbb', or a packed int
 * @param {string} [fallback='#000000']
 * @returns {string} lowercase '#rrggbb'
 */
export function normaliseHex(c, fallback = '#000000') {
  if (typeof c === 'number' && Number.isFinite(c)) {
    return '#' + (c & 0xffffff).toString(16).padStart(6, '0')
  }
  if (typeof c !== 'string') return fallback
  const s = c.trim()
  const withHash = s.startsWith('#') ? s : '#' + s
  if (FULL.test(withHash)) return withHash.toLowerCase()
  if (SHORT.test(withHash)) {
    const [, r, g, b] = withHash
    return ('#' + r + r + g + g + b + b).toLowerCase()
  }
  return fallback
}
