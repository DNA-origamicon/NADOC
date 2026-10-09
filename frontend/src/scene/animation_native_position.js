/** Historical topology may add/remove an insertion without removing its base site.
 * Only an explicit endpoint topology can authorize that absence. Keep ordinary
 * nativeMapPosition strict for malformed geometry and same-topology consumers.
 */
import { nativeMapPosition } from '../viewer/native_placement.js'
const endpointHelices = new WeakMap()
export function animationNativePosition(endpoint, nuc, copy = 0) {
  const first = endpoint?.posMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
  if (first?.nativeCopies?.[copy]) return nativeMapPosition(endpoint.posMap, nuc, copy)
  if (copy > 0 && endpoint?.displayDesign?.helices) {
    let helices = endpointHelices.get(endpoint)
    if (!helices) {
      helices = new Map(endpoint.displayDesign.helices.map(h => [h.id, h]))
      endpointHelices.set(endpoint, helices)
    }
    const helix = helices.get(nuc.helix_id)
    if (!helix) return undefined
    const delta = helix.loop_skips?.find(mark => mark.bp_index === nuc.bp_index)?.delta ?? 0
    if (copy >= 1 + delta) return undefined
  }
  return nativeMapPosition(endpoint?.posMap, nuc, copy)
}
