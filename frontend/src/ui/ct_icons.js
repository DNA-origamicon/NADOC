/**
 * Connection-type SVG icon library — shared by the per-part Overhangs Manager
 * and the assembly-level Overhangs Manager.
 *
 * Each renderer takes the user's overhang free-end polarities (L, R = '5p' /
 * '3p' / null), a `warn` flag (overlay a yellow ⚠ when the polarity combo
 * is forbidden for that connection type), and two stroke colors for the
 * LEFT / RIGHT overhang strands.
 *
 * Coordinates were tuned visually against the per-part popup. The icons are
 * a faithful port of `overhangs_manager_popup.js`'s `_ct*Svg` functions
 * (which is the source of truth — if a render here diverges, fix this file
 * to match that one).
 */

// ── Polarity helpers ─────────────────────────────────────────────────────────

export function oppPolarity(p) {
  if (p === '5p') return '3p'
  if (p === '3p') return '5p'
  return null
}

/** Render a 5'/3' marker at (x, y).
 *  - 5' → solid white square
 *  - 3' → triangle pointing in `dir` (cardinal or [dx,dy])
 *  Returns '' for null polarity (= side not yet selected). */
export function polarityMarker(x, y, dir, polarity, color = 'white') {
  if (polarity !== '5p' && polarity !== '3p') return ''
  const S = 3
  if (polarity === '5p') {
    return `<rect x="${x - S}" y="${y - S}" width="${S * 2}" height="${S * 2}" fill="${color}"/>`
  }
  let dx, dy
  if (Array.isArray(dir)) {
    [dx, dy] = dir
    const len = Math.hypot(dx, dy) || 1
    dx /= len; dy /= len
  } else {
    switch (dir) {
      case 'left':  dx = -1; dy = 0; break
      case 'right': dx =  1; dy = 0; break
      case 'up':    dx =  0; dy = -1; break
      case 'down':  dx =  0; dy =  1; break
      default:      dx =  1; dy =  0
    }
  }
  const ax = x + dx * S
  const ay = y + dy * S
  const px = -dy
  const py =  dx
  const b1x = x - dx * S + px * S
  const b1y = y - dy * S + py * S
  const b2x = x - dx * S - px * S
  const b2y = y - dy * S - py * S
  const f = (n) => Number.isInteger(n) ? `${n}` : n.toFixed(2)
  return `<polygon points="${f(ax)},${f(ay)} ${f(b1x)},${f(b1y)} ${f(b2x)},${f(b2y)}" fill="${color}"/>`
}

/** Yellow ⚠ triangle overlay centred in the tile, used when the selected
 *  L/R polarity pair is forbidden for that connection type. */
export function warningOverlay(viewW, viewH) {
  const cx = viewW / 2, cy = viewH / 2
  const r = Math.min(viewW, viewH) * 0.28
  const top   = `${cx},${cy - r}`
  const left  = `${cx - r * 0.9},${cy + r * 0.7}`
  const right = `${cx + r * 0.9},${cy + r * 0.7}`
  return `<g pointer-events="none">
    <polygon points="${top} ${left} ${right}"
             fill="#f5c518" stroke="#5a3a00" stroke-width="1.2" stroke-linejoin="round"/>
    <text x="${cx}" y="${cy + r * 0.4}" font-family="sans-serif" font-size="${r * 0.95}"
          font-weight="bold" text-anchor="middle" fill="#5a3a00">!</text>
  </g>`
}

// ── Direct connections ───────────────────────────────────────────────────────

function _endToRootSvg(L, R, warn, leftColor, rightColor) {
  return `
    <svg viewBox="0 0 100 36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84].map(x => `<line x1="${x}" y1="15" x2="${x}" y2="21"/>`).join('')}
      </g>
      <path d="M 6 14 L 86 14 L 86 6"
            stroke="${leftColor}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 14 30 L 14 22 L 94 22"
            stroke="${rightColor}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      ${polarityMarker(6,  14, 'left',  L, leftColor)}
      ${polarityMarker(94, 22, 'right', R, rightColor)}
      ${warn ? warningOverlay(100, 36) : ''}
    </svg>`
}

function _rootToRootSvg(L, R, warn, leftColor, rightColor) {
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[26,30,34,38,42,46,50,54,58,62,66,70,74,78,82,86].map(x => `<line x1="${x}" y1="19" x2="${x}" y2="25"/>`).join('')}
      </g>
      <line x1="18" y1="18" x2="92" y2="18" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="26" x2="92" y2="26" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="18" x2="18" y2="6"  stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="26" x2="18" y2="38" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${polarityMarker(92, 18, 'right', L, leftColor)}
      ${polarityMarker(92, 26, 'right', R, rightColor)}
      ${warn ? warningOverlay(100, 44) : ''}
    </svg>`
}

// ── Indirect (shared linker) ─────────────────────────────────────────────────

function _rootToRootIndirectSvg(L, R, warn, leftColor, rightColor) {
  const lL = oppPolarity(L), lR = oppPolarity(R)
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[10,14,18,22,26,30,34,38,42,46].map(x => `<line x1="${x}" y1="25" x2="${x}" y2="31"/>`).join('')}
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[54,58,62,66,70,74,78,82,86,90].map(x => `<line x1="${x}" y1="13" x2="${x}" y2="19"/>`).join('')}
      </g>
      <line x1="6" y1="32" x2="48" y2="32" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 6 24 L 50 24 L 50 20 L 94 20"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="52" y1="12" x2="94" y2="12" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="48" y1="32" x2="48" y2="40" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="52" y1="12" x2="52" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${polarityMarker(6,  32, 'left',  L,  leftColor)}
      ${polarityMarker(94, 12, 'right', R,  rightColor)}
      ${polarityMarker(6,  24, 'left',  lL, 'white')}
      ${polarityMarker(94, 20, 'right', lR, 'white')}
      ${warn ? warningOverlay(100, 44) : ''}
    </svg>`
}

function _endToEndIndirectSvg(L, R, warn, leftColor, rightColor) {
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[10,14,18,22,26,30,34,38,42,46].map(x => `<line x1="${x}" y1="25" x2="${x}" y2="31"/>`).join('')}
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[54,58,62,66,70,74,78,82,86,90].map(x => `<line x1="${x}" y1="13" x2="${x}" y2="19"/>`).join('')}
      </g>
      <line x1="6" y1="32" x2="48" y2="32" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 6 24 L 50 24 L 50 20 L 94 20"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="52" y1="12" x2="94" y2="12" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="6"  y1="32" x2="6"  y2="40" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="94" y1="12" x2="94" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${polarityMarker(48, 32, 'right', L, leftColor)}
      ${polarityMarker(52, 12, 'left',  R, rightColor)}
      ${polarityMarker(6,  24, 'left',  L, 'white')}
      ${polarityMarker(94, 20, 'right', R, 'white')}
      ${warn ? warningOverlay(100, 44) : ''}
    </svg>`
}

// ── ssDNA linkers (same-attach) ──────────────────────────────────────────────

function _rootToRootSsdnaLinkerSvg(L, R, warn, leftColor, rightColor) {
  const lL = oppPolarity(L), lR = oppPolarity(R)
  return _ssdnaLinkerSvg(leftColor, rightColor, /*leftStubX*/42, /*rightStubX*/58,
    /*leftMarkX*/6, /*rightMarkX*/94, /*leftMarkDir*/'left', /*rightMarkDir*/'right',
    L, R, lL, lR, warn)
}

function _endToEndSsdnaLinkerSvg(L, R, warn, leftColor, rightColor) {
  return _ssdnaLinkerSvg(leftColor, rightColor, 6, 94, 42, 58, 'right', 'left',
    L, R, L, R, warn)
}

function _mixedSsdnaLinkerSvg(leftIsRoot, rightIsRoot, L, R, warn, leftColor, rightColor) {
  const leftStubX  = leftIsRoot  ? 42 : 6
  const rightStubX = rightIsRoot ? 58 : 94
  const leftMarkX  = leftIsRoot  ? 6  : 42
  const rightMarkX = rightIsRoot ? 94 : 58
  const leftMarkDir  = leftIsRoot  ? 'left'  : 'right'
  const rightMarkDir = rightIsRoot ? 'right' : 'left'
  const lL = leftIsRoot  ? oppPolarity(L) : L
  const lR = rightIsRoot ? oppPolarity(R) : R
  return _ssdnaLinkerSvg(leftColor, rightColor, leftStubX, rightStubX,
    leftMarkX, rightMarkX, leftMarkDir, rightMarkDir, L, R, lL, lR, warn)
}

/** Shared ss-linker tile body. Two diagonally offset duplexes joined by a
 *  smooth ssDNA S-curve. Caller picks where the stubs/markers sit. */
function _ssdnaLinkerSvg(leftColor, rightColor, leftStubX, rightStubX,
                         leftMarkX, rightMarkX, leftMarkDir, rightMarkDir,
                         L, R, lL, lR, warn) {
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[10,14,18,22,26,30,34,38].map(x => `<line x1="${x}" y1="27" x2="${x}" y2="33"/>`).join('')}
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[62,66,70,74,78,82,86,90].map(x => `<line x1="${x}" y1="11" x2="${x}" y2="17"/>`).join('')}
      </g>
      <line x1="6"  y1="26" x2="42" y2="26" stroke="white"        stroke-width="2" stroke-linecap="round"/>
      <line x1="6"  y1="34" x2="42" y2="34" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="10" x2="94" y2="10" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="18" x2="94" y2="18" stroke="white"        stroke-width="2" stroke-linecap="round"/>
      <path d="M 42 26 C 50 26, 50 18, 58 18"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${leftStubX}"  y1="34" x2="${leftStubX}"  y2="40" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="${rightStubX}" y1="10" x2="${rightStubX}" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${polarityMarker(leftMarkX,  34, leftMarkDir,  L,  leftColor)}
      ${polarityMarker(rightMarkX, 10, rightMarkDir, R,  rightColor)}
      ${polarityMarker(6,  26, 'left',  lL, 'white')}
      ${polarityMarker(94, 18, 'right', lR, 'white')}
      ${warn ? warningOverlay(100, 44) : ''}
    </svg>`
}

// ── dsDNA linkers ────────────────────────────────────────────────────────────

function _rootToRootDsdnaLinkerSvg(L, R, warn, leftColor, rightColor) {
  // OUTER stubs (root-attach for ds = outer convention).
  return _dsdnaLinkerSvg(leftColor, rightColor, /*leftStubX*/4, /*rightStubX*/96,
    /*leftMarkX*/32, /*rightMarkX*/64, /*leftMarkDir*/'right', /*rightMarkDir*/'left',
    L, R, /*redL*/L, /*redR*/oppPolarity(L), /*grnL*/oppPolarity(R), /*grnR*/R, warn)
}

function _endToEndDsdnaLinkerSvg(L, R, warn, leftColor, rightColor) {
  // INNER stubs.
  return _dsdnaLinkerSvg(leftColor, rightColor, 32, 64, 4, 96, 'left', 'right',
    L, R, oppPolarity(L), L, R, oppPolarity(R), warn)
}

function _mixedDsdnaLinkerSvg(leftIsRoot, rightIsRoot, L, R, warn, leftColor, rightColor) {
  // Inverted dsDNA stub convention: root → OUTER stub; free → INNER stub.
  const leftStubX  = leftIsRoot  ? 4  : 32
  const rightStubX = rightIsRoot ? 96 : 64
  const leftMarkX  = leftIsRoot  ? 32 : 4
  const rightMarkX = rightIsRoot ? 64 : 96
  const leftMarkDir  = leftIsRoot  ? 'right' : 'left'
  const rightMarkDir = rightIsRoot ? 'left'  : 'right'
  const redL = leftIsRoot  ? L : oppPolarity(L)
  const redR = leftIsRoot  ? oppPolarity(L) : L
  const grnL = rightIsRoot ? oppPolarity(R) : R
  const grnR = rightIsRoot ? R : oppPolarity(R)
  return _dsdnaLinkerSvg(leftColor, rightColor, leftStubX, rightStubX,
    leftMarkX, rightMarkX, leftMarkDir, rightMarkDir, L, R, redL, redR, grnL, grnR, warn)
}

/** Shared ds-linker tile body. Two diagonally offset duplexes joined by a
 *  slanted dsDNA section with its own perpendicular base-pair hatching.
 *  Red + green strands trace the slanted linker; LEFT/RIGHT colors paint the
 *  overhang strands per side. */
function _dsdnaLinkerSvg(leftColor, rightColor, leftStubX, rightStubX,
                         leftMarkX, rightMarkX, leftMarkDir, rightMarkDir,
                         L, R, redL, redR, grnL, grnR, warn) {
  const RED = '#dc3545'
  const GREEN = '#27ae60'
  return `
    <svg viewBox="0 0 100 56" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[8,12,16,20,24,28].map(x => `<line x1="${x}" y1="43" x2="${x}" y2="49"/>`).join('')}
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="36" y1="32" x2="39.2" y2="38.4"/>
        <line x1="40" y1="30" x2="43.2" y2="36.4"/>
        <line x1="44" y1="28" x2="47.2" y2="34.4"/>
        <line x1="48" y1="26" x2="51.2" y2="32.4"/>
        <line x1="52" y1="24" x2="55.2" y2="30.4"/>
        <line x1="56" y1="22" x2="59.2" y2="28.4"/>
        <line x1="60" y1="20" x2="63.2" y2="26.4"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        ${[68,72,76,80,84,88,92].map(x => `<line x1="${x}" y1="11" x2="${x}" y2="17"/>`).join('')}
      </g>
      <line x1="4"  y1="50" x2="32" y2="50" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="64" y1="10" x2="96" y2="10" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 4 42 L 32 42 L 64 26"
            stroke="${RED}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 32 34 L 64 18 L 96 18"
            stroke="${GREEN}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${leftStubX}"  y1="50" x2="${leftStubX}"  y2="56" stroke="${leftColor}"  stroke-width="2" stroke-linecap="round"/>
      <line x1="${rightStubX}" y1="10" x2="${rightStubX}" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${polarityMarker(leftMarkX,  50, leftMarkDir,  L,    leftColor)}
      ${polarityMarker(rightMarkX, 10, rightMarkDir, R,    rightColor)}
      ${polarityMarker(4,  42, 'left',  redL, RED)}
      ${polarityMarker(64, 26, [ 32, -16], redR, RED)}
      ${polarityMarker(32, 34, [-32,  16], grnL, GREEN)}
      ${polarityMarker(96, 18, 'right', grnR, GREEN)}
      ${warn ? warningOverlay(100, 56) : ''}
    </svg>`
}

// ── Public dispatcher ────────────────────────────────────────────────────────

const _NEON_LEFT  = '#00e1ff'
const _NEON_RIGHT = '#ff36c6'

/** Build the SVG markup for a connection-type tile.
 *
 *  @param {string}      type         CT variant id (one of _VARIANTS' ids).
 *  @param {'5p'|'3p'|null} L         LEFT overhang free-end polarity.
 *  @param {'5p'|'3p'|null} R         RIGHT overhang free-end polarity.
 *  @param {boolean}     forbidden    Overlay the ⚠ when true.
 *  @param {boolean}     [hasA=L!=null] LEFT side actually has a selection.
 *  @param {boolean}     [hasB=R!=null] RIGHT side actually has a selection. */
export function ctTileSvg(type, L, R, forbidden, hasA, hasB) {
  if (hasA == null) hasA = L != null
  if (hasB == null) hasB = R != null
  const leftColor  = hasA ? _NEON_LEFT  : 'white'
  const rightColor = hasB ? _NEON_RIGHT : 'white'
  switch (type) {
    case 'root-to-root':              return _rootToRootSvg(L, R, forbidden, leftColor, rightColor)
    case 'root-to-root-indirect':     return _rootToRootIndirectSvg(L, R, forbidden, leftColor, rightColor)
    case 'end-to-end-indirect':       return _endToEndIndirectSvg(L, R, forbidden, leftColor, rightColor)
    case 'root-to-root-ssdna-linker': return _rootToRootSsdnaLinkerSvg(L, R, forbidden, leftColor, rightColor)
    case 'end-to-end-ssdna-linker':   return _endToEndSsdnaLinkerSvg(L, R, forbidden, leftColor, rightColor)
    case 'end-to-root-ssdna-linker':  return _mixedSsdnaLinkerSvg(false, true,  L, R, forbidden, leftColor, rightColor)
    case 'root-to-end-ssdna-linker':  return _mixedSsdnaLinkerSvg(true,  false, L, R, forbidden, leftColor, rightColor)
    case 'root-to-root-dsdna-linker': return _rootToRootDsdnaLinkerSvg(L, R, forbidden, leftColor, rightColor)
    case 'end-to-end-dsdna-linker':   return _endToEndDsdnaLinkerSvg(L, R, forbidden, leftColor, rightColor)
    case 'end-to-root-dsdna-linker':  return _mixedDsdnaLinkerSvg(false, true,  L, R, forbidden, leftColor, rightColor)
    case 'root-to-end-dsdna-linker':  return _mixedDsdnaLinkerSvg(true,  false, L, R, forbidden, leftColor, rightColor)
    case 'end-to-root':
    default:                          return _endToRootSvg(L, R, forbidden, leftColor, rightColor)
  }
}
