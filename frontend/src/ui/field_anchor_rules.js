/**
 * field_anchor_rules.js — the shared field/anchor guard rule, mirrored from the backend.
 *
 * Pure, no DOM, no fetch. Lifted verbatim out of `chain_sim_model.js` when the Chain
 * Simulations panel was removed (the mrDNA panel's M8 guard was its other consumer, and
 * a rule that mirrors `backend/core/field_anchor.py` should not live inside a UI panel's
 * model in the first place).
 */

// Mirror of backend field_anchor.surface_opposes_field: a hard surface holds a field that
// presses (anti-parallel) into its plane within ~25° (cos 25° ≈ 0.906), so a deposition
// stage (field into the floor) needs no strand anchor. Keep in lockstep with the backend.
const _OPPOSE_COS = 0.906
function _unit(v) {
  if (!Array.isArray(v) || v.length !== 3) return null
  const n = Math.hypot(v[0], v[1], v[2])
  return n > 1e-12 ? [v[0] / n, v[1] / n, v[2] / n] : null
}
/** True when a hard surface (`{dir}`) holds a field (`{dir}`) pressing into it — the
 * deposition case that needs no strand anchor. Exported so every field/anchor guard
 * shares this one mirror of the backend rule. */
export function surfaceOpposesField(field, surface) {
  const f = _unit(field?.dir)
  const s = _unit(surface?.dir)
  if (!f || !s) return false
  return f[0] * s[0] + f[1] * s[1] + f[2] * s[2] <= -_OPPOSE_COS
}
