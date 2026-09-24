/**
 * hairpin_dimer_window.js — the IDT-style structure window opened by clicking a
 * hairpin/self-dimer ⚠ (spreadsheet, Plates & tubes, Overhang Connections, in
 * both editors).
 *
 * Shows, for each flagged check, the structure primer3 found above threshold:
 * the hairpin as a stem–loop drawing, a self-/cross-dimer as an aligned duplex
 * (hairpin_dimer_structure.js), each with ΔG and Tm, plus the solution
 * conditions. One window at a time; Esc, backdrop or Close dismisses it.
 */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { dimerSvg, hairpinSvg } from './hairpin_dimer_structure.js'
import {
  HAIRPIN_DIMER_COLORS,
  HAIRPIN_DIMER_SEVERE_C,
  HAIRPIN_DIMER_THRESHOLD_C,
  buildHairpinDimerIndex,
  formatHairpinDimerConditions,
  formatHairpinDimerTooltip,
  hairpinDimerHits,
  hairpinDimerIconEl,
  hairpinDimerLevel,
  hairpinDimerSubject,
  overhangNameResolver,
} from './hairpin_dimer_report.js'

let _current = null

const LABEL = { hairpin: 'Hairpin', 'self-dimer': 'Self-dimer', 'cross-dimer': 'Cross-dimer' }

function _section(check, { nameOf, threshold, severe }) {
  const wrap = document.createElement('section')
  wrap.className = 'hd-window__check'
  wrap.style.cssText = 'margin-bottom:14px'
  const head = document.createElement('div')
  head.className = 'hd-window__subject'
  head.style.cssText = 'font-weight:600;margin-bottom:6px'
  head.textContent = hairpinDimerSubject(check, nameOf)
    + (check.status === 'partial' ? ' — N bases not evaluated' : '')
  wrap.appendChild(head)
  for (const { label, hit } of hairpinDimerHits(check, threshold)) {
    const critical = hit.tm > severe
    const cap = document.createElement('div')
    cap.className = `hd-window__caption hd-window__caption--${critical ? 'critical' : 'warning'}`
    cap.style.cssText = `font-size:12px;font-weight:600;margin:4px 0;color:${HAIRPIN_DIMER_COLORS[critical ? 'critical' : 'warning']}`
    cap.textContent = `⚠ ${LABEL[label] ?? label}${critical ? ` — Tm > ${severe} °C` : ''}`
    const fig = document.createElement('div')
    fig.className = `hd-window__figure hd-window__figure--${label}`
    fig.style.cssText = 'background:#fff;border:1px solid #d0d7de;border-radius:4px;'
      + 'overflow:auto;max-height:62vh;display:flex;justify-content:center'
    const svg = label === 'hairpin' ? hairpinSvg(hit, { fullLength: check.length }) : dimerSvg(hit)
    if (svg) fig.innerHTML = svg
    else {
      fig.style.color = '#111'
      fig.style.padding = '10px'
      fig.textContent = `Tm ${hit.tm} °C, ΔG ${hit.dg} kcal/mol (structure not available — re-run the check).`
    }
    wrap.append(cap, fig)
  }
  return wrap
}

/**
 * Open the structure window.
 * @param {object} o
 * @param {object[]} o.checks        flagged checks to show
 * @param {string}  [o.title]        e.g. the strand / overhang name
 * @param {Function} [o.nameOf]      overhang id → display name
 * @param {object}  [o.conditions]   report.conditions
 * @param {number}  [o.threshold]    amber above this Tm (report.threshold_c)
 * @param {number}  [o.severe]       red above this Tm (report.severe_threshold_c)
 */
export function openHairpinDimerWindow({ checks, title, nameOf, conditions, threshold, severe } = {}) {
  _current?.close()
  const t = threshold ?? HAIRPIN_DIMER_THRESHOLD_C
  const sv = severe ?? HAIRPIN_DIMER_SEVERE_C
  const body = document.createElement('div')
  body.className = 'hd-window__body'
  body.style.cssText = 'max-height:72vh;overflow:auto'
  for (const check of checks ?? []) body.appendChild(_section(check, { nameOf, threshold: t, severe: sv }))
  const foot = document.createElement('div')
  foot.className = 'hd-window__conditions'
  foot.style.cssText = 'font-size:11px;color:var(--color-text-muted,#8b949e)'
  foot.textContent = `Tm > ${t} °C amber, > ${sv} °C red · ${formatHairpinDimerConditions(conditions)} · ΔG at 37 °C · primer3`
  body.appendChild(foot)
  const modal = createModal({
    title: title ? `${title} — secondary structure` : 'Secondary structure',
    size: 'lg',
    body,
    className: 'hd-window',
    actions: [createButton({ label: 'Close', onClick: () => modal.close() })],
    onClose: () => { if (_current === modal) _current = null },
  })
  _current = modal
  modal.open()
  return modal
}

/** Open the window for every flagged, current check on *strandId*. */
export function openStrandHairpinDimerWindow(report, design, strandId, { title } = {}) {
  const checks = buildHairpinDimerIndex(report, design).byStrand.get(strandId)
  if (!checks?.length) return null
  return openHairpinDimerWindow({
    checks, title, nameOf: overhangNameResolver(design),
    conditions: report?.conditions, threshold: report?.threshold_c, severe: report?.severe_threshold_c,
  })
}

/**
 * Prepend a clickable ⚠ to *el* when *strandId* has flagged checks (spreadsheet
 * ID cells). Returns true when a badge was added.
 */
export function prependStrandWarningIcon(el, index, strandId, design, report, { title } = {}) {
  const checks = index.byStrand.get(strandId)
  if (!checks?.length) return false
  const nameOf = overhangNameResolver(design)
  const severe = report?.severe_threshold_c
  const tip = formatHairpinDimerTooltip(checks, { nameOf, threshold: report?.threshold_c, severe })
  el.prepend(hairpinDimerIconEl(tip, el.ownerDocument, () => openHairpinDimerWindow({
    checks, title, nameOf, conditions: report?.conditions, threshold: report?.threshold_c, severe,
  }), hairpinDimerLevel(checks, severe)))
  // The ID column is capped at 42 px; let a flagged cell widen instead of
  // ellipsizing the ID behind the badge.
  el.style.maxWidth = 'none'
  el.style.whiteSpace = 'nowrap'
  return true
}
