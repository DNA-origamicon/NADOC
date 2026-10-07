import { validateNativePlacement, placementIntegrityFailure } from './native_placement.js'
/** Backend-independent decoding of the existing NADOC geometry wire format.
 * This does not generate geometry or alter coordinate/identity conventions.
 * Keep source arrays shared between repeated assembly instances.
 * Package input validation belongs before this trusted wire decoder.
 */

export function expandCompactNucleotides(compact) {
  const flat = []
  if (!compact) return flat
  for (const helixId of Object.keys(compact)) {
    const byDir = compact[helixId]
    for (const dir of Object.keys(byDir)) {
      const b = byDir[dir]
      if (!b || !Array.isArray(b.bp)) placementIntegrityFailure({ helix_id: helixId, direction: dir }, 'bp', b?.bp, 'A compact geometry bucket must provide its site identities')
      const M = b.bp.length
      const copyCounts = new Map()
      for (let i = 0; i < M; i++) {
        const copy = copyCounts.get(b.bp[i]) ?? 0
        copyCounts.set(b.bp[i], copy + 1)
        flat.push({
          copy_k: copy,
          helix_id:          helixId,
          bp_index:          b.bp[i],
          direction:         dir,
          backbone_position: b.bb?.[i],
          base_position:     b.bs?.[i],
          base_normal:       b.bn?.[i],
          axis_tangent:      b.at?.[i],
          slab_position:     b.sp?.[i],
          slab_quaternion:   b.sq?.[i],
          placement_source:  b.pv?.[i],
          strand_id:         b.sid?.[i] ?? null,
          strand_type:       b.stype?.[i] ?? null,
          is_five_prime:     !!b.is5?.[i],
          is_three_prime:    !!b.is3?.[i],
          domain_index:      b.did?.[i] ?? 0,
          overhang_id:       b.ohid?.[i] ?? null,
          extension_id:      b.extid?.[i] ?? null,
          is_modification:   !!b.ismod?.[i],
          modification:      b.mod?.[i] ?? null,
          nucleobase:        b.base?.[i] ?? null,
        })
      }
    }
  }
  for (const nuc of flat) {
    validateNativePlacement(nuc)
  }
  return flat
}

/** Include occurrence index so repeated loop/insert sites never overwrite one another. */
export function positionUpdateLookup(compact) {
  const lookup = new Map()
  for (const [helixId, directions] of Object.entries(compact ?? {})) {
    for (const [direction, data] of Object.entries(directions)) {
      if (!data || !Array.isArray(data.bp)) placementIntegrityFailure({ helix_id: helixId, direction }, 'bp', data?.bp, 'A position update bucket must provide its site identities')
      const seen = new Map()
      for (let i = 0; i < (data?.bp?.length ?? 0); i++) {
        const bp = data.bp[i]
        const copy = seen.get(bp) ?? 0
        seen.set(bp, copy + 1)
        const nuc = { helix_id: helixId, bp_index: bp, direction, copy_k: copy,
          backbone_position: data.bb?.[i], base_position: data.bs?.[i],
          base_normal: data.bn?.[i], axis_tangent: data.at?.[i],
          slab_position: data.sp?.[i], slab_quaternion: data.sq?.[i],
          placement_source: data.pv?.[i], strand_id: data.sid?.[i] ?? null,
          extension_id: data.extid?.[i] ?? null,
          is_modification: !!data.ismod?.[i],
          modification: data.mod?.[i] ?? null }
        validateNativePlacement(nuc)
        lookup.set(`${helixId}:${bp}:${direction}:${copy}`, nuc)
      }
    }
  }
  return lookup
}

export function decodeAssemblyGeometry(json) {
  if (!json || !json.sources) return json
  // Decode each source's compact form once; shared across all referencing
  // instances. The arrays inside are the same JS objects in every entry.
  const decoded = {}
  for (const [srcKey, src] of Object.entries(json.sources)) {
    decoded[srcKey] = {
      nucleotides: src.nucleotides_compact
        ? expandCompactNucleotides(src.nucleotides_compact)
        : (src.nucleotides ?? []),
      helix_axes:  src.helix_axes,
      design:      src.design,
    }
  }

  const instances = {}
  for (const [instId, srcKey] of Object.entries(json.instances || {})) {
    const src = decoded[srcKey]
    instances[instId] = src
      ? { nucleotides: src.nucleotides, helix_axes: src.helix_axes, design: src.design }
      : { error: `unknown source key ${srcKey}` }
  }
  for (const [instId, msg] of Object.entries(json.errors || {})) {
    instances[instId] = { error: msg }
  }
  return { instances }
}
