// Highlight Undefined Bases — flags nucleotides whose assigned sequence is
// missing ('N') or whose whole strand has no sequence, painting them via the
// design renderer's undefined-highlight overlay. Lifted verbatim from main.js
// (the "Highlight Undefined Bases toggle" region) during the main.js carve-up.
//
// Two consumers share the on/off flag: this module owns the View-menu button +
// the design-change subscriber; the View-tool-buttons row (#41) flips the flag
// via the factory's isOn/setOn/refresh, and the scaffold-assign modal (#56)
// re-runs refresh after assigning a scaffold sequence.

/**
 * Pure core: given a design and the renderer's backbone entries, return the
 * subset of entries that should be highlighted as "undefined":
 *   - every nucleotide of a strand that has no sequence at all, OR
 *   - a nucleotide whose assigned character is 'N' (loop/skip-aware).
 *
 * @param {object} currentDesign  design with `helices` + `strands`
 * @param {Array}  backboneEntries  `designRenderer.getBackboneEntries()`
 * @returns {Array} the entries to highlight (possibly empty)
 */
export function computeUndefinedEntries(currentDesign, backboneEntries) {
  if (!currentDesign) return []

  // Build loop/skip map: "helixId:bp" → delta
  const lsMap = new Map()
  for (const helix of currentDesign.helices ?? []) {
    for (const ls of helix.loop_skips ?? []) {
      lsMap.set(`${helix.id}:${ls.bp_index}`, ls.delta)
    }
  }

  // Build a set of strand IDs with no sequence, and a set of "helixId:bp" keys
  // where the assigned character is 'N' (skip/loop-aware).
  const nullStrandIds = new Set()
  const nPosKeys      = new Set()

  for (const strand of currentDesign.strands ?? []) {
    if (!strand.sequence) {
      nullStrandIds.add(strand.id)
    } else {
      let seqIdx = 0
      for (const domain of strand.domains ?? []) {
        // Overhang domains: sequence is from overhang spec, not helix bp positions.
        // Advance seqIdx by domain length and skip position-level checking.
        if (domain.overhang_id != null) {
          seqIdx += Math.abs(domain.end_bp - domain.start_bp) + 1
          continue
        }
        const isForward = domain.direction === 'FORWARD'
        const step      = isForward ? 1 : -1
        const endBp     = domain.end_bp + step   // exclusive sentinel
        for (let bp = domain.start_bp; bp !== endBp; bp += step) {
          const delta = lsMap.get(`${domain.helix_id}:${bp}`) ?? 0
          if (delta <= -1) continue   // skip — no nucleotide in sequence
          const nCopies = delta + 1   // 1 for normal bp, 2 for loop (+1)
          let isN = false
          for (let c = 0; c < nCopies; c++) {
            if (strand.sequence[seqIdx] === 'N') isN = true
            seqIdx++
          }
          if (isN) nPosKeys.add(`${domain.helix_id}:${bp}`)
        }
      }
    }
  }

  return backboneEntries.filter(entry => {
    if (nullStrandIds.has(entry.nuc?.strand_id)) return true
    if (nPosKeys.has(`${entry.nuc?.helix_id}:${entry.nuc?.bp_index}`)) return true
    return false
  })
}

/**
 * Factory owning the undefined-highlight on/off state, the View-menu toggle
 * button, and the design-change re-highlight subscriber.
 *
 * @returns {{ isOn: () => boolean, setOn: (v: boolean) => void, refresh: () => void }}
 */
export function initUndefinedHighlight({ store, designRenderer, setMenuToggle }) {
  let _on = false

  function refresh() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { designRenderer.clearUndefinedHighlight(); return }
    const entries = computeUndefinedEntries(currentDesign, designRenderer.getBackboneEntries())
    if (entries.length > 0) {
      designRenderer.setUndefinedHighlight(entries)
    } else {
      designRenderer.clearUndefinedHighlight()
    }
  }

  document.getElementById('menu-view-undefined-bases')?.addEventListener('click', () => {
    _on = !_on
    setMenuToggle('menu-view-undefined-bases', _on)
    if (_on) {
      refresh()
    } else {
      designRenderer.clearUndefinedHighlight()
    }
  })

  // Refresh undefined highlight whenever the design changes (if toggle is on).
  store.subscribe((newState, prevState) => {
    if (_on && newState.currentDesign !== prevState.currentDesign) {
      refresh()
    }
  })

  return {
    isOn: () => _on,
    setOn: (v) => { _on = v },
    refresh,
  }
}
