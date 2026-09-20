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
      if (!b || !Array.isArray(b.bp)) continue
      const M = b.bp.length
      for (let i = 0; i < M; i++) {
        flat.push({
          helix_id:          helixId,
          bp_index:          b.bp[i],
          direction:         dir,
          backbone_position: b.bb[i],
          base_position:     b.bs[i],
          base_normal:       b.bn[i],
          axis_tangent:      b.at[i],
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
  return flat
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
