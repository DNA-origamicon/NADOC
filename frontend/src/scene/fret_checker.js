/**
 * Fluorescence + FRET Checker — two View-menu toggle modes that glow
 * fluorophores in the 3D scene.
 *
 *   Fluorescence: every supported fluorophore glows at full size.
 *   FRET:         same, but donors within their Förster radius of a compatible
 *                 acceptor are shrunk (scale 3 ≈ 1.5 nm radius) to signal energy
 *                 transfer. Both modes share one setFluorescenceGlow() call;
 *                 FRET takes priority on scale.
 *
 * Stateful: owns the two on/off flags, wires the menu toggles, subscribes to
 * geometry reloads, and is re-checked every frame while FRET is on (translate/
 * rotate moves update glow instantly). So it's a factory — pass dependencies in.
 * The distance test itself lives in fret_util.js (`fretQuenchedDonors`); the
 * pure lookup-table build (`buildFretLookups`) is exported + unit-tested here.
 *
 * Extracted verbatim from main.js's `// ── Fluorescence + FRET Checker` block.
 *
 * @param {object} deps
 * @param {object} deps.designRenderer — getFluoroEntries / setFluorescenceGlow / clearFluorescenceGlow
 * @param {object} deps.store          — subscribe(newState, prevState)
 * @param {Function} deps.setMenuToggle — (menuItemId, on) → updates the menu pill
 * @returns {{ refresh: Function, refreshIfFret: Function, isFretOn: Function }}
 */
import { FLUORO_EMISSION_COLORS } from './helix_renderer.js'
import { fretQuenchedDonors } from './fret_util.js'

// Förster radii (nm) for donor→acceptor pairs supported by NADOC modifications.
export const FRET_PAIRS = [
  { donor: 'cy3',     acceptor: 'cy5',     r0: 5.4 },
  { donor: 'fam',     acceptor: 'tamra',   r0: 4.6 },
  { donor: 'atto488', acceptor: 'atto550', r0: 6.3 },
  { donor: 'fam',     acceptor: 'bhq1',    r0: 4.2 },
  { donor: 'fam',     acceptor: 'bhq2',    r0: 4.2 },
  { donor: 'cy3',     acceptor: 'bhq2',    r0: 4.5 },
  { donor: 'tamra',   acceptor: 'bhq2',    r0: 4.5 },
]

// Sprite scale for a donor whose energy is being transferred (≈3 nm diameter).
const FRET_QUENCHED_SCALE = 3

/**
 * Pure: from a flat list of donor/acceptor/r0 pairs, build the two lookup tables
 * `fretQuenchedDonors` needs — donor → [acceptor keys] and "donor:acceptor" → r0.
 *
 * @param {{donor: string, acceptor: string, r0: number}[]} pairs
 * @returns {{ donorMap: Map<string,string[]>, r0Map: Map<string,number> }}
 */
export function buildFretLookups(pairs) {
  const donorMap = new Map()   // donor mod key → [acceptor mod keys]
  const r0Map    = new Map()   // "donor:acceptor" → r0 (nm)
  for (const { donor, acceptor, r0 } of pairs ?? []) {
    if (!donorMap.has(donor)) donorMap.set(donor, [])
    donorMap.get(donor).push(acceptor)
    r0Map.set(`${donor}:${acceptor}`, r0)
  }
  return { donorMap, r0Map }
}

export function initFretChecker({ designRenderer, store, setMenuToggle }) {
  let _fluorescenceOn = false
  let _fretOn         = false
  const { donorMap, r0Map } = buildFretLookups(FRET_PAIRS)

  function _refreshGlowModes() {
    if (!_fluorescenceOn && !_fretOn) { designRenderer.clearFluorescenceGlow(); return }

    const all      = designRenderer.getFluoroEntries()   // includes BHQ/Biotin for distance checks
    const quenched = _fretOn ? fretQuenchedDonors(all, donorMap, r0Map) : new Set()

    const entries = all
      .filter(fe => FLUORO_EMISSION_COLORS.has(fe.nuc?.modification))
      .map(fe => ({
        pos:          fe.pos,
        emissionColor: FLUORO_EMISSION_COLORS.get(fe.nuc.modification),
        scale:        quenched.has(fe) ? FRET_QUENCHED_SCALE : undefined,
      }))

    if (entries.length > 0) designRenderer.setFluorescenceGlow(entries)
    else                    designRenderer.clearFluorescenceGlow()
  }

  document.getElementById('menu-view-fluorescence')?.addEventListener('click', () => {
    _fluorescenceOn = !_fluorescenceOn
    setMenuToggle('menu-view-fluorescence', _fluorescenceOn)
    _refreshGlowModes()
  })

  document.getElementById('menu-view-fret')?.addEventListener('click', () => {
    _fretOn = !_fretOn
    setMenuToggle('menu-view-fret', _fretOn)
    _refreshGlowModes()
  })

  // Rebuild glow whenever the geometry reloads while either mode is on.
  store.subscribe((newState, prevState) => {
    if ((_fluorescenceOn || _fretOn) && newState.currentGeometry !== prevState.currentGeometry) {
      _refreshGlowModes()
    }
  })

  return {
    refresh: _refreshGlowModes,
    // Live FRET re-check from the render loop — runs every frame so translate/
    // rotate moves update glow instantly. No-op unless FRET is on.
    refreshIfFret: () => { if (_fretOn) _refreshGlowModes() },
    isFretOn: () => _fretOn,
  }
}
