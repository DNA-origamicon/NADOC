function vector3(value) {
  if (!Array.isArray(value) || value.length < 3) return null
  const out = value.slice(0, 3).map(Number)
  return out.every(Number.isFinite) ? out : null
}

function unit(value) {
  const v = vector3(value)
  if (!v) return null
  const length = Math.hypot(...v)
  return length > 1e-12 ? v.map(x => x / length) : null
}

function keyOf(nucleotide) {
  return `${nucleotide.helix_id}:${nucleotide.bp_index}:${nucleotide.direction}:${Number(nucleotide.copy) || 0}`
}

function signed(value, reverse) {
  return reverse && value !== 0 ? -value : value
}

/** Encode NADOC render geometry using oxDNA's rigid-nucleotide frame convention. */
export function nadocToOxdnaFrames(geometry) {
  if (!Array.isArray(geometry)) return []
  const frames = []
  for (const nucleotide of geometry) {
    const r = vector3(nucleotide?.backbone_position)
    const a1 = unit(nucleotide?.base_normal ?? [nucleotide?.nx, nucleotide?.ny, nucleotide?.nz])
    const tangent = unit(nucleotide?.axis_tangent ?? [nucleotide?.tx, nucleotide?.ty, nucleotide?.tz])
    if (!r || !a1 || !tangent) continue
    const reverse = String(nucleotide.direction).toUpperCase() === 'REVERSE'
    frames.push({
      key: keyOf(nucleotide), r, a1,
      a3: tangent.map(value => signed(value, reverse)),
      helix_id: nucleotide.helix_id, bp_index: nucleotide.bp_index,
      direction: nucleotide.direction, copy: Number(nucleotide.copy) || 0,
      strand_id: nucleotide.strand_id, domain_index: nucleotide.domain_index,
      strand_type: nucleotide.strand_type,
      overhang_id: nucleotide.overhang_id ?? null,
      nucleobase: nucleotide.nucleobase ?? nucleotide.base ?? null,
    })
  }
  return frames
}

/** Decode oxDNA rigid frames to the fields consumed by NADOC's native renderer. */
export function oxdnaFramesToNadoc(frames) {
  if (!Array.isArray(frames)) return []
  return frames.map(frame => {
    const reverse = String(frame.direction).toUpperCase() === 'REVERSE'
    const tangent = unit(frame.a3)?.map(value => signed(value, reverse))
    const normal = unit(frame.a1)
    const out = {
      helix_id: frame.helix_id, bp_index: frame.bp_index, direction: frame.direction,
      copy: Number(frame.copy) || 0, backbone_position: vector3(frame.r),
      base_normal: normal, axis_tangent: tangent,
    }
    if (normal) [out.nx, out.ny, out.nz] = normal
    if (tangent) [out.tx, out.ty, out.tz] = tangent
    return out
  }).filter(row => row.backbone_position && row.base_normal && row.axis_tangent)
}

function topologyEdges(frames) {
  const byStrand = new Map()
  frames.forEach((frame, index) => {
    if (frame.strand_id == null) return
    const strand = byStrand.get(frame.strand_id) ?? []
    strand.push({ index, domain: Number(frame.domain_index) || 0, bp: Number(frame.bp_index) || 0,
      reverse: String(frame.direction).toUpperCase() === 'REVERSE' })
    byStrand.set(frame.strand_id, strand)
  })
  const edges = []
  for (const strand of byStrand.values()) {
    strand.sort((a, b) => a.domain - b.domain ||
      (a.domain === b.domain ? (a.reverse ? b.bp - a.bp : a.bp - b.bp) : 0) || a.index - b.index)
    for (let i = 1; i < strand.length; i++) edges.push([strand[i - 1].index, strand[i].index])
  }
  return edges
}

/** One visible rigid-body centre per nucleotide plus oxDNA backbone connectivity. */
export function buildOxdnaInputPreview(geometry) {
  const frames = nadocToOxdnaFrames(geometry)
  return {
    frames,
    points: frames.map(frame => ({ x: frame.r[0], y: frame.r[1], z: frame.r[2] })),
    edges: topologyEdges(frames),
  }
}

/** Overlay simulated rigid-body coordinates onto the topology/metadata frames built
 * from the design. Updates use the same nucleotide identity as applyFemPositions. */
export function applySimulationToOxdnaFrames(frames, updates) {
  if (!Array.isArray(frames)) return []
  const byKey = new Map((updates ?? []).map(update => [keyOf(update), update]))
  return frames.map(frame => {
    const update = byKey.get(frame.key)
    if (!update) return frame
    const a1 = unit([update.nx, update.ny, update.nz])
    const a3 = unit([update.tx, update.ty, update.tz])
    let r = vector3(update.cm_position)
    const backbone = vector3(update.backbone_position)
    if (!r && backbone && a1 && a3) {
      const a2 = [
        a3[1] * a1[2] - a3[2] * a1[1],
        a3[2] * a1[0] - a3[0] * a1[2],
        a3[0] * a1[1] - a3[1] * a1[0],
      ]
      r = backbone.map((value, i) => value + (0.34 * a1[i] - 0.3408 * a2[i]) * 0.8518)
    }
    if (!r || !a1 || !a3) return frame
    return { ...frame, r, a1, a3 }
  })
}

/** Simulation/export representations never include inactive reference strands. */
export function activeDesignGeometry(geometry, design, hideReference = true) {
  if (!Array.isArray(geometry)) return []
  if (!hideReference) return geometry
  const references = new Set((design?.strands ?? []).filter(strand => strand?.is_reference).map(strand => strand.id))
  return references.size ? geometry.filter(nucleotide => !references.has(nucleotide?.strand_id)) : geometry
}
