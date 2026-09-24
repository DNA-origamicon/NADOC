/**
 * hairpin_dimer_report.js — pure helpers over the backend hairpin/self-dimer
 * report (POST /design/hairpin-dimer-check, backend/core/hairpin_dimer.py).
 *
 * The report is derived data, never persisted. Each check records the inputs
 * it analysed (assembled overhang bases, linker bridge, linker domain layout);
 * a check whose inputs no longer match the live design is STALE and is dropped
 * from the warning index, so an edited sequence never keeps an outdated ⚠.
 *
 * Check shapes (see the backend module docstring for scope):
 *   { key, kind: 'overhang'|'overhang_pair'|'linker', strand_id, overhang_ids,
 *     connection_id?, sequence, length, status, hairpin, dimer, max_tm, flagged,
 *     inputs: { overhangs: {id: seq}, bridge?, domains? } }
 *   hairpin / dimer: { tm, dg, dh, ds, offset, structure: string[] } | null
 */

import { assembleOverhangSequence } from '../scene/design_queries.js'

export const HAIRPIN_DIMER_THRESHOLD_C = 30   // flagged: amber ⚠
export const HAIRPIN_DIMER_SEVERE_C = 50      // critical: red ⚠

/** ⚠ colour per level (UI surfaces). The 3D / path-view glyphs keep their brighter amber. */
export const HAIRPIN_DIMER_COLORS = Object.freeze({ warning: '#d29922', critical: '#f85149' })

/** 'critical' | 'warning' | null for one check (backend `severity`, else from max_tm). */
export function hairpinDimerCheckLevel(check, severe = HAIRPIN_DIMER_SEVERE_C) {
  if (!check?.flagged) return null
  if (check.severity) return check.severity
  return check.max_tm > severe ? 'critical' : 'warning'
}

/** The worst level among *checks* — drives a strand's / overhang's glyph colour. */
export function hairpinDimerLevel(checks, severe = HAIRPIN_DIMER_SEVERE_C) {
  let level = null
  for (const c of checks ?? []) {
    const l = hairpinDimerCheckLevel(c, severe)
    if (l === 'critical') return 'critical'
    if (l) level = l
  }
  return level
}

/** Merge a check response into the current report. A full-scope response (or
 *  one for another design) replaces it; a partial one replaces checks by key. */
export function mergeHairpinDimerReport(prev, incoming) {
  if (!incoming) return prev ?? null
  const checks = incoming.checks ?? []
  if (!prev || incoming.scope === 'all' || prev.design_id !== incoming.design_id) {
    return { ...incoming, checks: [...checks] }
  }
  const byKey = new Map((prev.checks ?? []).map(c => [c.key, c]))
  for (const c of checks) byKey.set(c.key, c)
  return {
    ...prev,
    threshold_c: incoming.threshold_c,
    conditions: incoming.conditions,
    method: incoming.method,
    checks: [...byKey.values()],
  }
}

/** Same layout key as backend `hairpin_dimer.domains_signature`. */
export function domainsSignature(strand) {
  return (strand?.domains ?? [])
    .map(d => `${d.helix_id}:${d.start_bp}:${d.end_bp}:${d.direction}`)
    .join('|')
}

function _designLookups(design) {
  const strands = new Map((design?.strands ?? []).map(s => [s.id, s]))
  const overhangs = new Map((design?.overhangs ?? []).map(o => [o.id, o]))
  const conns = new Map((design?.overhang_connections ?? []).map(c => [c.id, c]))
  const domainLen = new Map()
  for (const s of design?.strands ?? []) {
    for (const d of s.domains ?? []) {
      if (d.overhang_id && !domainLen.has(d.overhang_id)) {
        domainLen.set(d.overhang_id, Math.abs(d.end_bp - d.start_bp) + 1)
      }
    }
  }
  const assembled = new Map()
  const overhangSeq = (id) => {
    if (!assembled.has(id)) {
      const spec = overhangs.get(id)
      const len = domainLen.get(id)
      assembled.set(id, spec && len != null ? assembleOverhangSequence(spec, len) : null)
    }
    return assembled.get(id)
  }
  return { strands, conns, overhangSeq }
}

function _isCurrent(check, lookups) {
  if (!lookups.strands.has(check.strand_id)) return false
  const inputs = check.inputs ?? {}
  for (const [id, seq] of Object.entries(inputs.overhangs ?? {})) {
    if (lookups.overhangSeq(id) !== seq) return false
  }
  if ('bridge' in inputs) {
    const conn = lookups.conns.get(check.connection_id)
    if (!conn || String(conn.bridge_sequence ?? '').toUpperCase() !== inputs.bridge) return false
  }
  if ('domains' in inputs && domainsSignature(lookups.strands.get(check.strand_id)) !== inputs.domains) {
    return false
  }
  return true
}

/** True when *check* still describes the live *design*. */
export function isHairpinDimerCheckCurrent(check, design) {
  return _isCurrent(check, _designLookups(design))
}

const _EMPTY_INDEX = Object.freeze({
  byStrand: new Map(), byOverhang: new Map(), byConnection: new Map(), flagged: [],
})

/**
 * Index the flagged, still-current checks of *report* against *design*.
 *   byStrand     strand id  → checks (overhang, pair and linker checks)
 *   byOverhang   overhang id → overhang + pair checks involving it
 *   byConnection connection id → linker-strand checks
 */
export function buildHairpinDimerIndex(report, design) {
  if (!report || !design || report.design_id !== design.id) return _EMPTY_INDEX
  const flaggedChecks = (report.checks ?? []).filter(c => c.flagged)
  if (!flaggedChecks.length) return _EMPTY_INDEX
  const lookups = _designLookups(design)
  const index = { byStrand: new Map(), byOverhang: new Map(), byConnection: new Map(), flagged: [] }
  const push = (map, key, check) => {
    if (key == null) return
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(check)
  }
  for (const check of flaggedChecks) {
    if (!_isCurrent(check, lookups)) continue
    index.flagged.push(check)
    push(index.byStrand, check.strand_id, check)
    if (check.kind === 'linker') push(index.byConnection, check.connection_id, check)
    else for (const id of check.overhang_ids ?? []) push(index.byOverhang, id, check)
  }
  return index
}

/** Memoize `buildHairpinDimerIndex` on the (report, design) identities. */
export function createHairpinDimerIndexCache() {
  let lastReport, lastDesign, lastIndex = _EMPTY_INDEX
  return {
    get(report, design) {
      if (report !== lastReport || design !== lastDesign) {
        lastReport = report
        lastDesign = design
        lastIndex = buildHairpinDimerIndex(report, design)
      }
      return lastIndex
    },
  }
}

// ── Live targets / re-check / marker anchors ─────────────────────────────────

/**
 * What the backend would check in *design*: overhang ids (not auxiliary, with a
 * backing domain on a non-reference strand) and linker strand ids. Mirrors
 * `backend.core.hairpin_dimer._live_overhangs` + the linker loop.
 */
export function hairpinDimerTargets(design) {
  const strands = new Map((design?.strands ?? []).map(s => [s.id, s]))
  const backed = new Set()
  for (const s of design?.strands ?? []) {
    if (s.is_reference) continue
    for (const d of s.domains ?? []) if (d.overhang_id) backed.add(d.overhang_id)
  }
  const overhangIds = (design?.overhangs ?? [])
    .filter(o => !o.auxiliary_endpoint && backed.has(o.id) && !strands.get(o.strand_id)?.is_reference)
    .map(o => o.id)
  const linkerIds = (design?.strands ?? [])
    .filter(s => s.strand_type === 'linker' && !s.is_reference)
    .map(s => s.id)
  return { overhangIds, linkerIds }
}

/**
 * Targets whose check is missing or stale against *design* — what a live
 * checker must (re)request: `{ overhang_ids, strand_ids }` (strand_ids = linkers).
 */
export function hairpinDimerRecheckTargets(report, design) {
  const { overhangIds, linkerIds } = hairpinDimerTargets(design)
  const sameDesign = report && design && report.design_id === design.id
  const byKey = new Map(sameDesign ? (report.checks ?? []).map(c => [c.key, c]) : [])
  const lookups = _designLookups(design)
  const need = key => { const c = byKey.get(key); return !c || !_isCurrent(c, lookups) }
  return {
    overhang_ids: overhangIds.filter(id => need(`overhang:${id}`)),
    strand_ids: linkerIds.filter(id => need(`linker:${id}`)),
  }
}

/**
 * One marker per flagged strand for the 3D view / cadnano path view:
 * `{ strandId, checks, domains, label, tooltip }`. `domains` locate the flagged
 * structure — the flagged overhang's backing domain, or a linker's domains.
 */
export function hairpinDimerMarkers(report, design) {
  const index = buildHairpinDimerIndex(report, design)
  if (!index.flagged.length) return []
  const strands = new Map((design.strands ?? []).map(s => [s.id, s]))
  const nameOf = overhangNameResolver(design)
  const rank = { overhang: 0, overhang_pair: 1, linker: 2 }
  const out = []
  for (const [strandId, checks] of index.byStrand) {
    const strand = strands.get(strandId)
    if (!strand) continue
    const primary = [...checks].sort((a, b) => rank[a.kind] - rank[b.kind])[0]
    const ovhg = primary.kind === 'linker' ? null : primary.overhang_ids[0]
    const domains = ovhg
      ? (strand.domains ?? []).filter(d => d.overhang_id === ovhg)
      : (strand.domains ?? [])
    out.push({
      strandId,
      checks,
      domains,
      label: strand.name || (ovhg ? nameOf(ovhg) : 'Linker strand'),
      level: hairpinDimerLevel(checks, report?.severe_threshold_c),
      tooltip: formatHairpinDimerTooltip(checks, {
        nameOf, threshold: report?.threshold_c, severe: report?.severe_threshold_c,
      }),
    })
  }
  return out
}

// ── Text ────────────────────────────────────────────────────────────────────

const _fmt = x => (Math.round(x * 10) / 10).toFixed(1)

function _hitText(label, hit) {
  return `${label} Tm ${_fmt(hit.tm)} °C (ΔG₃₇ ${_fmt(hit.dg)} kcal/mol)`
}

/** What a check analysed, e.g. "Overhang OH-A (22 nt)" or "Linker strand (50 nt)". */
export function hairpinDimerSubject(check, nameOf) {
  const name = id => nameOf?.(id) || id
  if (check.kind === 'overhang') return `Overhang ${name(check.overhang_ids[0])} (${check.length} nt)`
  if (check.kind === 'overhang_pair') {
    return `Overhangs ${name(check.overhang_ids[0])} × ${name(check.overhang_ids[1])} (copy–copy)`
  }
  return `Linker strand (${check.length} nt)`
}

/** Hits above threshold, strongest first: [{ label, hit }]. */
export function hairpinDimerHits(check, threshold = HAIRPIN_DIMER_THRESHOLD_C) {
  const out = []
  if (check.hairpin && check.hairpin.tm > threshold) out.push({ label: 'hairpin', hit: check.hairpin })
  if (check.dimer && check.dimer.tm > threshold) {
    out.push({ label: check.kind === 'overhang_pair' ? 'cross-dimer' : 'self-dimer', hit: check.dimer })
  }
  return out.sort((a, b) => b.hit.tm - a.hit.tm)
}

/** One summary line per check, e.g. "Overhang OH1 (20 nt): hairpin Tm 42.1 °C (ΔG₃₇ −0.4 kcal/mol)". */
export function formatHairpinDimerLine(check, { nameOf, threshold } = {}) {
  const hits = hairpinDimerHits(check, threshold ?? HAIRPIN_DIMER_THRESHOLD_C)
  const partial = check.status === 'partial' ? ' [N bases not evaluated]' : ''
  return `${hairpinDimerSubject(check, nameOf)}: ${hits.map(h => _hitText(h.label, h.hit)).join('; ')}${partial}`
}

/** "10 mM Mg²⁺, 0 mM Na⁺, 200 nM oligo" — the solution the report was computed for. */
export function formatHairpinDimerConditions(c) {
  if (!c) return ''
  return `${c.mg_mM ?? '?'} mM Mg²⁺, ${c.na_mM ?? '?'} mM Na⁺, ${c.conc_nM ?? '?'} nM oligo`
}

/** Short inline form, e.g. "hairpin Tm 42.1 °C · self-dimer Tm 35.0 °C". */
export function formatHairpinDimerCompact(checks, { threshold } = {}) {
  const t = threshold ?? HAIRPIN_DIMER_THRESHOLD_C
  return (checks ?? [])
    .flatMap(c => hairpinDimerHits(c, t))
    .sort((a, b) => b.hit.tm - a.hit.tm)
    .map(h => `${h.label} Tm ${_fmt(h.hit.tm)} °C`)
    .join(' · ')
}

/**
 * Multi-line tooltip for a set of flagged checks. `withStructure` appends the
 * strongest structure diagram (only legible in a monospace tooltip).
 */
export function formatHairpinDimerTooltip(checks, { nameOf, threshold, severe, withStructure = false } = {}) {
  const t = threshold ?? HAIRPIN_DIMER_THRESHOLD_C
  const sv = severe ?? HAIRPIN_DIMER_SEVERE_C
  const lines = [hairpinDimerLevel(checks, sv) === 'critical'
    ? `⚠ Strong secondary structure — Tm > ${sv} °C`
    : `⚠ Secondary structure with Tm > ${t} °C`]
  for (const c of checks ?? []) lines.push(formatHairpinDimerLine(c, { nameOf, threshold: t }))
  if (withStructure) {
    const top = (checks ?? [])
      .flatMap(c => hairpinDimerHits(c, t))
      .sort((a, b) => b.hit.tm - a.hit.tm)[0]
    if (top?.hit.structure?.length) lines.push('', `Strongest (${top.label}):`, ...top.hit.structure)
  }
  return lines.join('\n')
}

/** Overhang id → user-facing name (label, else id). */
export function overhangNameResolver(design) {
  const byId = new Map((design?.overhangs ?? []).map(o => [o.id, o]))
  return id => byId.get(id)?.label || byId.get(id)?.name || id
}

/** strand id → { text (tooltip), level }, for every strand with a flagged, current check. */
export function hairpinDimerStrandWarnings(index, design, { threshold, severe, withStructure = false } = {}) {
  const nameOf = overhangNameResolver(design)
  const out = new Map()
  for (const [sid, checks] of index.byStrand) {
    out.set(sid, {
      text: formatHairpinDimerTooltip(checks, { nameOf, threshold, severe, withStructure }),
      level: hairpinDimerLevel(checks, severe),
    })
  }
  return out
}

/**
 * Compact inline ⚠ badge with a hover tooltip; shared by every warning surface.
 * With `onClick` it becomes a button (the structure window) and swallows the
 * click so the row / well underneath does not also react.
 */
export function hairpinDimerIconEl(title, doc = document, onClick = null, level = 'warning') {
  const el = doc.createElement('span')
  el.className = `hd-warn-icon hd-warn-icon--${level === 'critical' ? 'critical' : 'warning'}`
  el.textContent = '⚠'
  el.title = onClick ? `${title}\n\nClick to show the structure.` : title
  el.setAttribute('aria-label', title)
  el.style.cssText = `color:${HAIRPIN_DIMER_COLORS[level] ?? HAIRPIN_DIMER_COLORS.warning};`
    + 'font-weight:700;margin-right:3px;cursor:' + (onClick ? 'pointer' : 'help')
  if (onClick) {
    el.setAttribute('role', 'button')
    el.tabIndex = 0
    const fire = ev => { ev.preventDefault(); ev.stopPropagation(); onClick(ev) }
    el.addEventListener('click', fire)
    el.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') fire(ev) })
  }
  return el
}
