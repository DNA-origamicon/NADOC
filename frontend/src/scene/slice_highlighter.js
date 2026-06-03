/**
 * Slice-plane bead highlighter extracted from main.js.
 *
 * `sliceTargetKeys` is the PURE geometry core (which beads the slice plane crosses
 * at a given offset/plane). `initSliceHighlighter` is the stateful factory: it owns
 * the set of currently-recoloured entries and drives designRenderer to paint /
 * revert them (same DI shape as initEndExtrudeArrows / measurement_tool). The
 * slice-plane *toggle* orchestration stays in main.js. Unit-tested in
 * slice_highlighter.test.js.
 */
import { BDNA_RISE_PER_BP } from '../constants.js'

const NORMAL_AXIS = { XY: 'z', XZ: 'y', YZ: 'x' }

/**
 * Set of "helixId::bpIndex" keys for the beads the slice plane crosses.
 * @param {object} design  current Design (helices with axis_start, bp_start, length_bp)
 * @param {number} offsetNm  slice-plane offset along the plane normal
 * @param {'XY'|'XZ'|'YZ'} plane
 */
export function sliceTargetKeys(design, offsetNm, plane) {
  const keys = new Set()
  if (!design) return keys
  const axis = NORMAL_AXIS[plane] ?? 'z'
  for (const helix of design.helices ?? []) {
    const z0 = helix.axis_start[axis]
    const bp = Math.round(helix.bp_start + (offsetNm - z0) / BDNA_RISE_PER_BP)
    if (bp < helix.bp_start || bp >= helix.bp_start + helix.length_bp) continue
    keys.add(`${helix.id}::${bp}`)
  }
  return keys
}

/**
 * @param {object} deps
 * @param {object} deps.designRenderer  needs getBackboneEntries, getSlabEntries, setEntryColor
 * @param {() => object} deps.getDesign  returns the current Design
 * @returns {{ update: (offsetNm:number, plane:string)=>void, clear: ()=>void }}
 */
export function initSliceHighlighter({ designRenderer, getDesign }) {
  let highlighted = []

  function clear() {
    for (const entry of highlighted) designRenderer.setEntryColor(entry, entry.defaultColor)
    highlighted = []
  }

  function update(offsetNm, plane) {
    clear()
    const keys = sliceTargetKeys(getDesign(), offsetNm, plane)
    if (!keys.size) return
    const paint = (entries) => {
      for (const entry of entries) {
        if (keys.has(`${entry.nuc.helix_id}::${entry.nuc.bp_index}`)) {
          designRenderer.setEntryColor(entry, 0xffffff)
          highlighted.push(entry)
        }
      }
    }
    paint(designRenderer.getBackboneEntries())
    paint(designRenderer.getSlabEntries())
  }

  return { update, clear }
}
