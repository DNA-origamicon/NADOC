/**
 * Flexible-tether connection builder extracted from main.js (deduped from
 * _buildRelaxPayload and _buildSsdnaPayload, which had the identical loop). Pure.
 * Unit-tested in flex_tethers.test.js.
 */
import { flexAnchorKey } from './design_queries.js'

/**
 * For the cluster being moved, the {movingKey, fixedKey, contour} of each flexible
 * connection touching it — moving = the anchor on `movingClusterId`, fixed = the
 * other end. Keys are "helix:bp:dir" (or dropped if either anchor can't resolve).
 */
export function flexTetherConnections(conns, movingClusterId, design) {
  const out = []
  for (const c of (conns ?? [])) {
    if (c.cluster_a_id !== movingClusterId && c.cluster_b_id !== movingClusterId) continue
    const onA = c.cluster_a_id === movingClusterId
    const movingKey = flexAnchorKey(onA ? c.anchor_a : c.anchor_b, design)
    const fixedKey  = flexAnchorKey(onA ? c.anchor_b : c.anchor_a, design)
    if (movingKey && fixedKey) out.push({ movingKey, fixedKey, contour: c.contour_length_nm })
  }
  return out
}
