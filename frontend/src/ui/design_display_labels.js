/** Pure, human-facing labels for strands and selected bases. */

import { baseKey, parseBaseKey, XB_HELIX } from '../scene/base_ref.js'

const BASE_TYPE_ORDER = Object.freeze([
  'Scaffold', 'Staple', 'OH', 'Extension', 'Extra base', 'Linker', 'Base',
])

const strandType = strand => strand?.strand_type?.value ?? strand?.strand_type ?? null

function strandPrefix(strand) {
  const type = strandType(strand)
  if (type === 'staple') return 'S'
  if (type === 'linker' || String(strand?.id ?? '').startsWith('__lnk__')) return 'L'
  return 'X'
}

/** Stable-for-this-design 1-based display ordinals, independent of spreadsheet sort. */
export function buildStrandDisplayIdMap(strands = []) {
  const counts = { S: 0, L: 0, X: 0 }
  const labels = new Map()
  for (const strand of strands ?? []) {
    if (!strand?.id || labels.has(strand.id)) continue
    const prefix = strandPrefix(strand)
    labels.set(strand.id, `${prefix}${++counts[prefix]}`)
  }
  return labels
}

export function strandDisplayId(strandId, design) {
  if (!strandId) return '—'
  return buildStrandDisplayIdMap(design?.strands).get(strandId) ?? '—'
}

/** Match the viewport/pathview convention: explicit helix label, otherwise array index. */
export function helixDisplayLabel(design, helixId) {
  const helices = design?.helices ?? []
  const index = helices.findIndex(helix => helix.id === helixId)
  if (index < 0) return '?'
  const explicit = helices[index]?.label
  return explicit == null || explicit === '' ? String(index) : String(explicit)
}

function compressNumbers(values) {
  const sorted = [...new Set(values.filter(Number.isFinite))].sort((a, b) => a - b)
  const tokens = []
  for (let start = 0; start < sorted.length;) {
    let end = start
    while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end++
    const length = end - start + 1
    if (length >= 3) tokens.push(`${sorted[start]}-${sorted[end]}`)
    else for (let i = start; i <= end; i++) tokens.push(String(sorted[i]))
    start = end + 1
  }
  return tokens
}

function terminalAnchor(extension, strand) {
  const domains = strand?.domains ?? []
  if (!domains.length) return null
  const domain = extension?.end === 'five_prime' ? domains[0] : domains.at(-1)
  return {
    helixId: domain.helix_id,
    bp: extension?.end === 'five_prime' ? domain.start_bp : domain.end_bp,
  }
}

function geometryIndex(geometry) {
  const byKey = new Map()
  for (const nuc of geometry ?? []) {
    const key = baseKey(nuc, nuc.copy_k ?? nuc.copy ?? 0)
    if (key && !byKey.has(key)) byKey.set(key, nuc)
  }
  return byKey
}

function ordinaryType(nuc, strand) {
  const type = nuc?.strand_type?.value ?? nuc?.strand_type ?? strandType(strand)
  if (nuc?.overhang_id || type === 'oh_binder') return 'OH'
  if (type === 'scaffold') return 'Scaffold'
  if (type === 'staple') return 'Staple'
  if (type === 'linker') return 'Linker'
  return 'Base'
}

function typeRank(type) {
  const rank = BASE_TYPE_ORDER.indexOf(type)
  return rank < 0 ? BASE_TYPE_ORDER.length : rank
}

/**
 * Canonical base keys → grouped labels such as:
 *   Staple - 1[34,35]
 *   Linker - 44[10-22]
 *
 * Extension and crossover-insert bases use their parent helix and anchor bp because
 * their canonical keys live on synthetic helices with local indices.
 */
export function selectedBaseDisplayGroups(keys, design, geometry = []) {
  const strands = design?.strands ?? []
  const strandById = new Map(strands.map(strand => [strand.id, strand]))
  const extensionById = new Map((design?.extensions ?? []).map(ext => [ext.id, ext]))
  const crossoverById = new Map([
    ...(design?.crossovers ?? []), ...(design?.forced_ligations ?? []),
  ].map(crossover => [crossover.id, crossover]))
  const nucByKey = geometryIndex(geometry)
  const domainsByHelix = new Map()
  for (const strand of strands) {
    for (const domain of strand.domains ?? []) {
      let domains = domainsByHelix.get(domain.helix_id)
      if (!domains) domainsByHelix.set(domain.helix_id, (domains = []))
      domains.push({ strand, domain })
    }
  }
  const groups = new Map()

  function designOwner(parsed) {
    const direction = String(parsed.direction ?? '').toUpperCase()
    return (domainsByHelix.get(parsed.helix_id) ?? []).find(({ domain }) => {
      const lo = Math.min(domain.start_bp, domain.end_bp)
      const hi = Math.max(domain.start_bp, domain.end_bp)
      return parsed.bp_index >= lo && parsed.bp_index <= hi
        && String(domain.direction ?? '').toUpperCase() === direction
    }) ?? null
  }

  function add(type, helix, token) {
    const key = `${type}\u0000${helix}`
    let group = groups.get(key)
    if (!group) {
      group = { type, helix, numeric: [], decorated: [] }
      groups.set(key, group)
    }
    if (typeof token === 'number') group.numeric.push(token)
    else if (token != null && token !== '') group.decorated.push(String(token))
  }

  for (const key of keys ?? []) {
    const parsed = parseBaseKey(key)
    if (!parsed) continue

    if (parsed.helix_id === XB_HELIX) {
      const crossover = crossoverById.get(parsed.crossover_id)
      const half = crossover?.half_a ?? (crossover?.three_prime_helix_id != null ? {
        helix_id: crossover.three_prime_helix_id, index: crossover.three_prime_bp,
      } : null)
      add('Extra base', helixDisplayLabel(design, half?.helix_id),
        half ? `${half.index}+${parsed.k + 1}` : `?+${parsed.k + 1}`)
      continue
    }

    if (parsed.helix_id.startsWith('__ext_')) {
      const extension = extensionById.get(parsed.helix_id.slice('__ext_'.length))
      const strand = strandById.get(extension?.strand_id)
      const anchor = terminalAnchor(extension, strand)
      add('Extension', helixDisplayLabel(design, anchor?.helixId),
        anchor ? `${anchor.bp}›${parsed.bp_index + 1}` : `?›${parsed.bp_index + 1}`)
      continue
    }

    const liveNuc = nucByKey.get(key)
    const owner = liveNuc ? null : designOwner(parsed)
    const nuc = liveNuc ?? (owner ? {
      strand_id: owner.strand.id, strand_type: strandType(owner.strand),
      overhang_id: owner.domain.overhang_id ?? null,
    } : null)
    const strand = owner?.strand ?? strandById.get(nuc?.strand_id)
    const type = parsed.helix_id.startsWith('__lnk__') ? 'Linker' : ordinaryType(nuc, strand)
    const helix = helixDisplayLabel(design, parsed.helix_id)
    const token = parsed.copy > 0 ? `${parsed.bp_index}+loop${parsed.copy}` : parsed.bp_index
    add(type, helix, token)
  }

  return [...groups.values()]
    .sort((a, b) => typeRank(a.type) - typeRank(b.type)
      || String(a.helix).localeCompare(String(b.helix), undefined, { numeric: true }))
    .map(group => {
      const decorated = [...new Set(group.decorated)]
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      const indices = [...compressNumbers(group.numeric), ...decorated]
      return { type: group.type, helix: group.helix, indices,
        location: `${group.helix}[${indices.join(',')}]` }
    })
}

/** One display row per type, with multiple helices kept in the same type cluster. */
export function selectedBaseDisplayRows(keys, design, geometry = []) {
  const rows = []
  for (const group of selectedBaseDisplayGroups(keys, design, geometry)) {
    let row = rows.find(item => item.type === group.type)
    if (!row) { row = { type: group.type, locations: [] }; rows.push(row) }
    row.locations.push(group.location)
  }
  return rows.map(row => ({ ...row, label: `${row.type} - ${row.locations.join(', ')}` }))
}
