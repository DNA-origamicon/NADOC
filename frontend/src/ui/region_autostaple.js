// Autostaple command: whole structure, or only the staples touching a selected
// region. The backend grows the region to every staple that touches it and keeps
// all other staples (ids, crossovers, sequences) exactly; see
// backend/api/part_autostaple_command.py. A region is a list of inclusive bp
// intervals per helix (both directions) — positions, so the recorded feature
// replays after upstream edits.
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { canonicalSelection } from '../scene/selection_model.js'
import { parseBaseKey } from '../scene/base_ref.js'

export const AUTOSTAPLE_SCOPE_TITLE = 'Autostaple scope'

const span = (helix_id, a, b) => ({ helix_id, lo_bp: Math.min(a, b), hi_bp: Math.max(a, b) })
const domainSpans = strand => (strand?.domains ?? []).map(d => span(d.helix_id, d.start_bp, d.end_bp))

/** Merge overlapping/adjacent spans per real helix, in design helix order. */
export function mergeRegion(design, spans) {
  const order = new Map((design?.helices ?? []).map((h, i) => [h.id, i]))
  const byHelix = new Map()
  for (const s of spans) {
    if (!order.has(s.helix_id) || !Number.isInteger(s.lo_bp) || !Number.isInteger(s.hi_bp)) continue
    if (!byHelix.has(s.helix_id)) byHelix.set(s.helix_id, [])
    byHelix.get(s.helix_id).push(s)
  }
  const region = []
  for (const helixId of [...byHelix.keys()].sort((a, b) => order.get(a) - order.get(b))) {
    const sorted = byHelix.get(helixId).sort((a, b) => a.lo_bp - b.lo_bp)
    let current = null
    for (const s of sorted) {
      if (current && s.lo_bp <= current.hi_bp + 1) current.hi_bp = Math.max(current.hi_bp, s.hi_bp)
      else { current = { ...s }; region.push(current) }
    }
  }
  return region
}

/** Region covered by the canonical 3D selection (strands, domains, bases, ends, bonds, crossovers, clusters, overhangs). */
export function selectionRegion(state) {
  const design = state?.currentDesign
  if (!design) return []
  const strands = new Map((design.strands ?? []).map(s => [s.id, s]))
  const helices = new Map((design.helices ?? []).map(h => [h.id, h]))
  const spans = []
  const base = key => { const b = parseBaseKey(key); if (b && Number.isInteger(b.bp_index)) spans.push(span(b.helix_id, b.bp_index, b.bp_index)) }
  for (const ref of canonicalSelection(state).items) {
    if (ref.kind === 'strand') spans.push(...domainSpans(strands.get(ref.id)))
    else if (ref.kind === 'domain') {
      const d = strands.get(ref.strandId)?.domains?.[ref.domainIndex]
      if (d) spans.push(span(d.helix_id, d.start_bp, d.end_bp))
    } else if (ref.kind === 'base' || ref.kind === 'end') base(ref.key)
    else if (ref.kind === 'bond') { base(ref.fromKey); base(ref.toKey) }
    else if (ref.kind === 'crossover') {
      const x = (design.crossovers ?? []).find(item => item.id === ref.id)
      if (x) for (const h of [x.half_a, x.half_b]) spans.push(span(h.helix_id, h.index, h.index))
      const f = (design.forced_ligations ?? []).find(item => item.id === ref.id)
      if (f) spans.push(span(f.three_prime_helix_id, f.three_prime_bp, f.three_prime_bp), span(f.five_prime_helix_id, f.five_prime_bp, f.five_prime_bp))
    } else if (ref.kind === 'cluster') {
      const cluster = (design.cluster_transforms ?? []).find(item => item.id === ref.id)
      for (const id of cluster?.helix_ids ?? []) {
        const h = helices.get(id)
        if (h) spans.push(span(id, h.bp_start, h.bp_start + h.length_bp - 1))
      }
    } else if (ref.kind === 'overhang') {
      for (const s of strands.values()) for (const d of s.domains ?? [])
        if (d.overhang_id === ref.id) spans.push(span(d.helix_id, d.start_bp, d.end_bp))
    }
  }
  return mergeRegion(design, spans)
}

/** Region covered by a plain strand-id selection (cadnano editor). */
export function strandRegion(design, strandIds = []) {
  const strands = new Map((design?.strands ?? []).map(s => [s.id, s]))
  return mergeRegion(design, strandIds.flatMap(id => domainSpans(strands.get(id))))
}

/** Ask whether to restaple only the selected region. Resolves 'region' | 'all' | null. */
export function chooseAutostapleScope(region) {
  const helixCount = new Set(region.map(item => item.helix_id)).size
  return new Promise(resolve => {
    let choice = null
    const pick = value => () => { choice = value; modal.close() }
    const body = el('div', { children: [
      el('p', { text: `The selection covers ${region.length} bp span${region.length === 1 ? '' : 's'} on ${helixCount} ${helixCount === 1 ? 'helix' : 'helices'}.` }),
      el('p', { className: 'tool-help', text: 'Selection only restaples every staple that touches the selection. All other staples, their crossovers and sequences stay exactly as they are.' }),
    ] })
    const modal = createModal({ title: AUTOSTAPLE_SCOPE_TITLE, body, actions: [
      createButton({ label: 'Cancel', onClick: () => modal.close() }),
      createButton({ label: 'Entire structure', onClick: pick('all') }),
      createButton({ label: 'Selection only', variant: 'primary', onClick: pick('region') }),
    ], onClose: () => resolve(choice) })
    modal.root.setAttribute('aria-label', AUTOSTAPLE_SCOPE_TITLE)
    modal.open()
  })
}

/**
 * Menu command. With a selection, offer selection-only vs entire structure;
 * without one, autostaple the entire structure as before.
 */
export async function runAutostapleCommand({ design, region = [], autostaple, lastError, toast, showProgress, hideProgress, choose = chooseAutostapleScope }) {
  if (!design?.helices?.length) { toast('No design loaded.', { severity: 'error' }); return null }
  let scope = 'all'
  if (region.length) {
    scope = await choose(region)
    if (!scope) return null
  }
  const regional = scope === 'region'
  showProgress(regional ? 'Region autostaple' : 'Full autostaple',
    regional ? 'Restapling the selected region…' : 'Assigning sequences and routing staples…')
  let result
  try { result = await autostaple({ scaffold_name: 'M13mp18', ...(regional ? { region } : {}) }) } finally { hideProgress() }
  if (!result) {
    toast(`${regional ? 'Region' : 'Full'} autostaple failed: ${lastError()?.message ?? 'unknown error'}`, { severity: 'error' })
    return null
  }
  const report = result.full_autostaple ?? {}
  toast(regional
    ? `Region autostaple complete: restapled ${report.region?.restapled ?? 0} staple(s); ${report.region?.kept ?? 0} kept unchanged.`
    : `Full autostaple complete: ${report.auto_crossover?.placed ?? 0} crossovers placed.`)
  return result
}
