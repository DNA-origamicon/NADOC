import { CELL_H, GROUP_GAP, PAIR_Y, ROW_H, RULER_H, TOP_PAD, connectedCellGroups } from './layout.js'

/** Read authored longitudinal connections; equal cells alone do not join rows.
 * Mirrors backbone_continuations.py's Sweep attachment recognition. No molecular
 * data is rewritten: every member retains its own helix and frame identity.
 */
export function continuedHelixGroups(design) {
  const helices = design?.helices ?? []
  const byId = new Map(helices.map(h => [h.id, h]))
  const parent = new Map(helices.map(h => [h.id, h.id]))
  const root = id => {
    while (parent.get(id) !== id) id = parent.get(id)
    return id
  }
  const attachments = new Map()
  for (const op of design?.deformations ?? []) {
    if (op.type !== 'sweep' || op.params?.start_step !== 1) continue
    const direction = op.params.direction
    const boundary = direction === 1 ? op.plane_a_bp : op.plane_b_bp
    const members = new Set(op.affected_helix_ids ?? [])
    for (const id of members) {
      const list = attachments.get(id) ?? []
      list.push({ direction, boundary, members })
      attachments.set(id, list)
    }
    // The live Sweep feature also certifies attachment when both strands have
    // subsequently been nicked at the boundary (or were not ligated on creation).
    const feature = (design?.feature_log ?? []).find(f => !f.suppressed && f.op_kind === 'sweep' &&
      op.id === `sweep_${f.params?.sweep_id}`)
    const source = feature && !feature.params.detach_source && byId.get(feature.params.source_helix_id)
    if (!source) continue
    const owners = h => (design.cluster_transforms ?? []).filter(c => c.helix_ids?.includes(h.id)).map(c => c.id).sort().join('|')
    const sourceOwners = owners(source)
    for (const id of members) {
      const h = byId.get(id)
      if (!h?.grid_pos) continue
      const candidates = helices.filter(old => !members.has(old.id) &&
        old.lattice_frame_id === source.lattice_frame_id && old.direction === h.direction &&
        old.grid_pos?.[0] === h.grid_pos[0] && old.grid_pos?.[1] === h.grid_pos[1] &&
        owners(old) === sourceOwners &&
        (direction === 1 ? old.bp_start + old.length_bp === boundary && h.bp_start === boundary
          : old.bp_start === boundary + 1 && h.bp_start + h.length_bp === boundary + 1))
      if (candidates.length === 1) parent.set(root(id), root(candidates[0].id))
    }
  }
  const slot = (id, bp, dir) => JSON.stringify([id, bp, dir])
  const forced = new Map((design?.forced_ligations ?? [])
    .map(fl => [`${slot(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction)}:${slot(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)}`, fl]))
  const attached = (newId, newBp, sourceId, sourceBp) =>
    (attachments.get(newId) ?? []).some(a => newBp === a.boundary &&
      sourceBp === a.boundary - a.direction && !a.members.has(sourceId))
  for (const strand of design?.strands ?? []) {
    if (strand.is_reference) continue
    const domains = strand.domains ?? []
    for (let i = 1; i < domains.length; i++) {
      const a = domains[i - 1], b = domains[i]
      if (a.overhang_id || b.overhang_id || a.binds_overhang_id || b.binds_overhang_id) continue
      const ha = byId.get(a.helix_id), hb = byId.get(b.helix_id)
      if (!ha || !hb || ha.id === hb.id || a.direction !== b.direction ||
          ha.direction !== hb.direction || !ha.grid_pos || !hb.grid_pos ||
          ha.grid_pos[0] !== hb.grid_pos[0] || ha.grid_pos[1] !== hb.grid_pos[1] ||
          b.start_bp !== a.end_bp + (a.direction === 'FORWARD' ? 1 : -1)) continue
      const [low, high] = ha.bp_start < hb.bp_start ? [ha, hb] : [hb, ha]
      if (low.bp_start + low.length_bp !== high.bp_start) continue
      const explicit = forced.get(`${slot(ha.id, a.end_bp, a.direction)}:${slot(hb.id, b.start_bp, b.direction)}`)
      const sweep = ha.lattice_frame_id != null && hb.lattice_frame_id != null &&
        ha.lattice_frame_id !== hb.lattice_frame_id &&
        (attached(ha.id, a.end_bp, hb.id, b.start_bp) || attached(hb.id, b.start_bp, ha.id, a.end_bp))
      if (explicit ? !explicit.extra_bases?.length : sweep) parent.set(root(hb.id), root(ha.id))
    }
  }
  const groups = new Map()
  for (const h of helices) {
    const key = root(h.id)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(h)
  }
  // Ambiguous overlapping/branched records remain separate and inspectable.
  const indices = new Map(helices.map((h, i) => [h.id, i]))
  return [...groups.values()].flatMap(members => {
    const sorted = [...members].sort((a, b) => a.bp_start - b.bp_start)
    return sorted.some((h, i) => i && sorted[i - 1].bp_start + sorted[i - 1].length_bp > h.bp_start)
      ? members.map(h => [h]) : [members]
  }).sort((a, b) => indices.get(a[0].id) - indices.get(b[0].id))
}

export function buildContinuedRows(design, { cellOf, forwardOf, nativeOrientation = true }) {
  const nativeIndex = new Map((design?.helices ?? []).map((h, i) => [h.id, i]))
  const groups = continuedHelixGroups(design)
  if (!nativeOrientation) groups.reverse()
  const cells = groups.map(group => cellOf(group[0]))
  const components = connectedCellGroups(cells)
  const rowMap = new Map(), rows = []
  let fwdY = RULER_H + TOP_PAD
  groups.forEach((members, i) => {
    if (i && components[i] !== components[i - 1]) fwdY += GROUP_GAP
    const source = members[0]
    const info = { fwdY, revY: fwdY + PAIR_Y, scaffoldFwd: forwardOf(source, cells[i]),
      cell: cells[i], idx: nativeIndex.get(source.id), label: source.label ?? null }
    for (const h of members) rowMap.set(h.id, info)
    const middle = fwdY + CELL_H / 2
    rows.push({ hid: source.id, hids: members.map(h => h.id), members: [...members].sort((a, b) => a.bp_start - b.bp_start),
      info, lo: middle - ROW_H / 2, hi: middle + ROW_H / 2 })
    fwdY += ROW_H
  })
  return { rowMap, rows }
}

export function continuedHelixLabels(design) {
  const indices = new Map((design?.helices ?? []).map((h, i) => [h.id, i]))
  return new Map(continuedHelixGroups(design).flatMap(group =>
    group.map(h => [h.id, group[0].label ?? indices.get(group[0].id)])))
}

/** Address a visible row by bp, including its two outer extension regions. */
export function helixAtRowBp(row, bp) {
  if (!row) return null
  return (row.members.find(h => bp < h.bp_start + h.length_bp) ?? row.members.at(-1))?.id ?? null
}

export function reorderContinuedRows(rows, selected, gap, nativeOrientation) {
  const chosen = row => row.hids.some(id => selected.has(id))
  const moving = rows.filter(chosen)
  if (!moving.length) return null
  const rest = rows.filter(row => !chosen(row))
  const insertAt = rows.slice(0, gap).filter(row => !chosen(row)).length
  const result = [...rest.slice(0, insertAt), ...moving, ...rest.slice(insertAt)]
  if (result.every((row, i) => row === rows[i])) return null
  if (!nativeOrientation) result.reverse()
  return result.flatMap(row => row.hids)
}

export function rowPaintRanges(row, lo, hi) {
  return (row?.members ?? []).flatMap((h, i, members) => {
    const start = i === 0 ? lo : Math.max(lo, h.bp_start)
    const end = i === members.length - 1 ? hi : Math.min(hi, members[i + 1].bp_start - 1)
    return start <= end ? [{ helixId: h.id, lo: start, hi: end }] : []
  })
}
