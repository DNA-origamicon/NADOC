/**
 * hairpin_dimer_structure.js — pure drawing of the structure behind a
 * hairpin/self-dimer ⚠, in the style of IDT OligoAnalyzer.
 *
 * Input is one hit from the backend report (`backend/core/hairpin_dimer.py`):
 *   { tm, dg, offset, structure: string[] } — `structure` is primer3's ASCII:
 *   hairpin → [slashLine, sequence]   ('/' opens, '\' closes, '-' unpaired)
 *   dimer   → [s1 unpaired, s1 paired, s2 paired, s2 unpaired]  (s2 3'→5')
 *
 * primer3's hairpin model is a single stem–loop whose stem may carry bulges and
 * internal loops (never a multibranch loop), so a deterministic layout covers
 * every case: the stem as a vertical ladder, loop gaps bowed outward, the
 * hairpin loop on a circle, 5'/3' tails splayed downward. Output is SVG markup
 * (a string) so it can be unit-tested without a browser.
 */

const PAIR_W = 46       // distance between the two bases of a pair
const ROW = 26          // vertical step along the stem
const STEP = 26         // backbone spacing in loops / tails
const MARGIN = 44
const BASE_R = 8        // backbone lines stop this far from a letter
const DOT_R = 6
const CHAR_W = 11       // dimer alignment column width
const TAIL_MAX = 8      // unpaired 5'/3' tail bases drawn before eliding the rest

export const PAIR_COLOR = { GC: '#e3211c', AT: '#3f3ab5', other: '#8b949e' }

function _pairKind(a, b) {
  const s = `${a}${b}`.toUpperCase()
  if (s === 'GC' || s === 'CG') return 'GC'
  if (s === 'AT' || s === 'TA') return 'AT'
  return 'other'
}

const _esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
const _f = x => Math.round(x * 10) / 10
const _caption = hit => `ΔG = ${Number(hit.dg).toFixed(2)} kcal/mol · Tm = ${Number(hit.tm).toFixed(1)} °C`

// ── Hairpin ────────────────────────────────────────────────────────────────

/** primer3 hairpin ASCII → { seq, pairs: [[i, j]] (0-based, i < j, outermost first), offset }. */
export function parseHairpinStructure(hit) {
  const [slash = '', seq = ''] = hit?.structure ?? []
  const stack = []
  const pairs = []
  for (let i = 0; i < slash.length; i++) {
    if (slash[i] === '/') stack.push(i)
    else if (slash[i] === '\\' && stack.length) pairs.push([stack.pop(), i])
  }
  pairs.sort((a, b) => a[0] - b[0])
  return { seq: seq.toUpperCase(), pairs, offset: hit?.offset ?? 0 }
}

/** Solve the loop circle: the closing pair spans PAIR_W, each of m+1 other chords STEP. */
function _loopRadius(m) {
  const f = R => 2 * Math.asin(Math.min(1, PAIR_W / (2 * R)))
    + (m + 1) * 2 * Math.asin(Math.min(1, STEP / (2 * R))) - 2 * Math.PI
  let lo = Math.max(PAIR_W, STEP) / 2, hi = (m + 2) * Math.max(PAIR_W, STEP)
  for (let k = 0; k < 60; k++) {
    const mid = (lo + hi) / 2
    if (f(mid) > 0) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

/**
 * Base coordinates (y up) for a single stem–loop; null when there is no pair.
 * Tails longer than `tailMax` are elided: only bases first..last get positions.
 */
export function layoutHairpin(seq, pairs, { tailMax = TAIL_MAX } = {}) {
  if (!pairs.length) return null
  const n = seq.length
  const pos = new Array(n).fill(null)
  const [i0, j0] = pairs[0]
  pos[i0] = [-PAIR_W / 2, 0]
  pos[j0] = [PAIR_W / 2, 0]
  let y = 0
  for (let k = 1; k < pairs.length; k++) {
    const [ia, ja] = pairs[k - 1]
    const [ib, jb] = pairs[k]
    const left = ib - ia - 1, right = ja - jb - 1
    const yb = y + (Math.max(left, right) + 1) * ROW
    for (let t = 1; t <= left; t++) {           // bulge / internal loop, bowed outward
      const u = t / (left + 1)
      pos[ia + t] = [-PAIR_W / 2 - Math.sin(Math.PI * u) * ROW * 0.9, y + u * (yb - y)]
    }
    for (let t = 1; t <= right; t++) {
      const u = t / (right + 1)
      pos[ja - t] = [PAIR_W / 2 + Math.sin(Math.PI * u) * ROW * 0.9, y + u * (yb - y)]
    }
    pos[ib] = [-PAIR_W / 2, yb]
    pos[jb] = [PAIR_W / 2, yb]
    y = yb
  }
  const [ik, jk] = pairs[pairs.length - 1]
  const m = jk - ik - 1
  const R = _loopRadius(m)
  const alpha = 2 * Math.asin(Math.min(1, PAIR_W / (2 * R)))
  const beta = 2 * Math.asin(Math.min(1, STEP / (2 * R)))
  const h = Math.sqrt(Math.max(0, R * R - (PAIR_W / 2) ** 2)) * (alpha <= Math.PI ? 1 : -1)
  const cy = y + h
  const thetaL = Math.atan2(y - cy, -PAIR_W / 2)
  for (let t = 1; t <= m; t++) {                // clockwise from the left base, over the top
    const a = thetaL - t * beta
    pos[ik + t] = [R * Math.cos(a), cy + R * Math.sin(a)]
  }
  const splay = [0.45, -0.89]                     // tails diverge downward like IDT's
  const first = i0 - Math.min(i0, tailMax)
  const last = j0 + Math.min(n - 1 - j0, tailMax)
  for (let t = 1; t <= i0 - first; t++) pos[i0 - t] = [pos[i0][0] - splay[0] * STEP * t, splay[1] * STEP * t]
  for (let t = 1; t <= last - j0; t++) pos[j0 + t] = [pos[j0][0] + splay[0] * STEP * t, splay[1] * STEP * t]
  return { pos, loopCenter: [0, cy], first, last }
}

/**
 * SVG for a hairpin hit: letters, backbone, G·C (red) / A·T (blue) pair dots,
 * every-10th position ticks (numbered in the full analysed sequence), 5'/3'
 * ends and a ΔG / Tm caption. `fullLength` (the analysed sequence's length)
 * lets an end label count bases outside the drawn window, e.g. "5′ +40 nt".
 * Returns '' when the hit has no pairs.
 */
export function hairpinSvg(hit, { fullLength } = {}) {
  const { seq, pairs, offset } = parseHairpinStructure(hit)
  const lay = layoutHairpin(seq, pairs)
  if (!lay) return ''
  const { loopCenter, first, last } = lay
  const pos = lay.pos
  const partner = new Map()
  for (const [i, j] of pairs) { partner.set(i, j); partner.set(j, i) }

  // Outward direction for a tick / end label.
  const outward = i => {
    let dx, dy
    if (partner.has(i)) { const p = pos[partner.get(i)]; dx = pos[i][0] - p[0]; dy = 0 }
    else if (i > pairs[0][0] && i < pairs[0][1] && pos[i][1] >= pos[pairs.at(-1)[0]][1]) {
      dx = pos[i][0] - loopCenter[0]; dy = pos[i][1] - loopCenter[1]
    } else { dx = pos[i][0]; dy = 0 }
    const L = Math.hypot(dx, dy) || 1
    return [dx / L, dy / L]
  }

  const tickLen = 34
  const extra = []
  const shown = pos.filter(Boolean)
  const xs = shown.map(p => p[0]), ys = shown.map(p => p[1])
  const minX = Math.min(...xs) - tickLen - 30, maxX = Math.max(...xs) + tickLen + 30
  const minY = Math.min(...ys) - 44, maxY = Math.max(...ys) + 20
  const W = maxX - minX + 2 * MARGIN
  const H = maxY - minY + 2 * MARGIN + 24
  const X = x => _f(x - minX + MARGIN)
  const Y = y => _f(maxY - y + MARGIN)

  const parts = []
  for (let i = first; i < last; i++) {
    const [ax, ay] = pos[i], [bx, by] = pos[i + 1]
    const d = Math.hypot(bx - ax, by - ay)
    if (d <= 2 * BASE_R) continue
    const ux = (bx - ax) / d, uy = (by - ay) / d
    parts.push(`<line x1="${X(ax + ux * BASE_R)}" y1="${Y(ay + uy * BASE_R)}" x2="${X(bx - ux * BASE_R)}" y2="${Y(by - uy * BASE_R)}" stroke="#222" stroke-width="1.2"/>`)
  }
  for (const [i, j] of pairs) {
    const kind = _pairKind(seq[i], seq[j])
    const mx = (pos[i][0] + pos[j][0]) / 2, my = (pos[i][1] + pos[j][1]) / 2
    parts.push(`<circle class="hd-pair hd-pair--${kind}" cx="${X(mx)}" cy="${Y(my)}" r="${DOT_R}" fill="${PAIR_COLOR[kind]}"/>`)
  }
  for (let i = first; i <= last; i++) {
    parts.push(`<text x="${X(pos[i][0])}" y="${Y(pos[i][1])}" class="hd-base">${_esc(seq[i])}</text>`)
    const num = offset + i + 1
    if (num % 10 === 0) {
      const [ox, oy] = outward(i)
      const x1 = pos[i][0] + ox * 12, y1 = pos[i][1] + oy * 12
      const x2 = pos[i][0] + ox * tickLen, y2 = pos[i][1] + oy * tickLen
      parts.push(`<line x1="${X(x1)}" y1="${Y(y1)}" x2="${X(x2)}" y2="${Y(y2)}" stroke="#222" stroke-width="0.8"/>`)
      extra.push(`<text x="${X(x2 + ox * 12)}" y="${Y(y2 + oy * 12)}" class="hd-tick">${num}</text>`)
    }
  }
  // End labels continue the tail direction; bases outside the drawing (elided
  // tail, or outside primer3's 60-nt window) are counted, with a dashed stub.
  const total = fullLength ?? offset + seq.length
  const endLabel = (i, inward, label, hidden) => {
    const nb = pos[inward] ?? [pos[i][0], pos[i][1] + 1]
    const dx = pos[i][0] - nb[0], dy = pos[i][1] - nb[1]
    const L = Math.hypot(dx, dy) || 1
    const ux = dx / L, uy = dy / L
    const d = hidden > 0 ? 34 : 20
    let out = ''
    if (hidden > 0) {
      out += `<line x1="${X(pos[i][0] + ux * BASE_R)}" y1="${Y(pos[i][1] + uy * BASE_R)}" x2="${X(pos[i][0] + ux * 22)}" y2="${Y(pos[i][1] + uy * 22)}" stroke="#222" stroke-width="1.2" stroke-dasharray="2 3"/>`
    }
    const text = hidden > 0 ? `${label} +${hidden} nt` : label
    return out + `<text x="${X(pos[i][0] + ux * d)}" y="${Y(pos[i][1] + uy * d)}" class="hd-end">${text}</text>`
  }
  extra.push(
    endLabel(first, first + 1, "5′", offset + first),
    endLabel(last, last - 1, "3′", total - (offset + last + 1)),
  )
  const caption = _caption(hit)
  return `<svg xmlns="http://www.w3.org/2000/svg" class="hd-structure hd-structure--hairpin" width="${_f(W)}" height="${_f(H)}" viewBox="0 0 ${_f(W)} ${_f(H)}" role="img" aria-label="Hairpin: ${_esc(caption)}">`
    + '<style>.hd-base{font:600 14px monospace;text-anchor:middle;dominant-baseline:central;fill:#111}'
    + '.hd-tick,.hd-end{font:11px monospace;text-anchor:middle;dominant-baseline:central;fill:#111}'
    + '.hd-caption{font:12px monospace;text-anchor:middle;fill:#111}</style>'
    + `<rect width="100%" height="100%" fill="#fff"/>${parts.join('')}${extra.join('')}`
    + `<text x="${_f(W / 2)}" y="${_f(H - 14)}" class="hd-caption">${_esc(caption)}</text></svg>`
}

// ── Dimer ──────────────────────────────────────────────────────────────────

/** primer3 dimer ASCII → aligned rows { top, bars, bottom } (bars: '|' where paired). */
export function parseDimerStructure(hit) {
  const [l1 = '', l2 = '', l3 = '', l4 = ''] = hit?.structure ?? []
  const width = Math.max(l1.length, l2.length, l3.length, l4.length)
  const isBase = ch => /[ACGTN]/i.test(ch ?? '')
  let top = '', bars = '', bottom = ''
  for (let c = 0; c < width; c++) {
    const p = l2[c], q = l3[c]
    top += isBase(p) ? p : (isBase(l1[c]) ? l1[c] : ' ')
    bottom += isBase(q) ? q : (isBase(l4[c]) ? l4[c] : ' ')
    bars += isBase(p) && isBase(q) ? '|' : ' '
  }
  // Drop columns blank in all three rows at either end.
  let a = 0, b = width
  const blank = c => top[c] === ' ' && bottom[c] === ' '
  while (a < b && blank(a)) a++
  while (b > a && blank(b - 1)) b--
  return { top: top.slice(a, b).toUpperCase(), bars: bars.slice(a, b), bottom: bottom.slice(a, b).toUpperCase() }
}

/** IDT-style dimer alignment: strand 1 5'→3' over strand 2 3'→5', coloured pair bars. */
export function dimerSvg(hit) {
  const { top, bars, bottom } = parseDimerStructure(hit)
  if (!bars.includes('|')) return ''
  const lead = 30
  const W = lead * 2 + top.length * CHAR_W + 2 * 16
  const H = 118
  const x = c => _f(16 + lead + c * CHAR_W + CHAR_W / 2)
  const rows = { top: 34, bars: 52, bottom: 70 }
  const parts = []
  for (let c = 0; c < top.length; c++) {
    if (top[c] !== ' ') parts.push(`<text x="${x(c)}" y="${rows.top}" class="hd-base">${_esc(top[c])}</text>`)
    if (bottom[c] !== ' ') parts.push(`<text x="${x(c)}" y="${rows.bottom}" class="hd-base">${_esc(bottom[c])}</text>`)
    if (bars[c] === '|') {
      const kind = _pairKind(top[c], bottom[c])
      parts.push(`<line class="hd-pair hd-pair--${kind}" x1="${x(c)}" y1="${rows.bars - 7}" x2="${x(c)}" y2="${rows.bars + 7}" stroke="${PAIR_COLOR[kind]}" stroke-width="3"/>`)
    }
  }
  const caption = _caption(hit)
  const ends = row => [row.search(/\S/), row.length - 1 - [...row].reverse().join('').search(/\S/)]
  const [t0, t1] = ends(top), [b0, b1] = ends(bottom)
  const endX = c => _f(16 + lead + c * CHAR_W + CHAR_W / 2)
  return `<svg xmlns="http://www.w3.org/2000/svg" class="hd-structure hd-structure--dimer" width="${_f(W)}" height="${H}" viewBox="0 0 ${_f(W)} ${H}" role="img" aria-label="Dimer: ${_esc(caption)}">`
    + '<style>.hd-base{font:600 14px monospace;text-anchor:middle;dominant-baseline:central;fill:#111}'
    + '.hd-end{font:11px monospace;text-anchor:middle;dominant-baseline:central;fill:#111}'
    + '.hd-caption{font:12px monospace;text-anchor:middle;fill:#111}</style>'
    + `<rect width="100%" height="100%" fill="#fff"/>`
    + `<text x="${endX(t0 - 1.6)}" y="${rows.top}" class="hd-end">5′</text><text x="${endX(t1 + 1.6)}" y="${rows.top}" class="hd-end">3′</text>`
    + `<text x="${endX(b0 - 1.6)}" y="${rows.bottom}" class="hd-end">3′</text><text x="${endX(b1 + 1.6)}" y="${rows.bottom}" class="hd-end">5′</text>`
    + parts.join('')
    + `<text x="${_f(W / 2)}" y="${H - 16}" class="hd-caption">${_esc(caption)}</text></svg>`
}
