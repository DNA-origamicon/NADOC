/**
 * Help ▸ About this file — a read-only summary of the open design.
 *
 * `showAboutFileModal({ api, path })` fetches GET /design/about and renders:
 *   • topology counts (total bases, strands, helices)
 *   • loadouts and features per loadout
 *   • oxDNA + MD jobs with their on-disk sizes, and the total disk footprint
 *   • assemblies that currently use this part
 *
 * `path` is the workspace-relative .nadoc path of the open file (null for an
 * unsaved design — the disk-keyed sections then read "design not yet saved").
 * Pure presentation: it only reads from the backend, never mutates anything.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { formatBytes } from './format_bytes.js'

const _DIM = 'color:#8b949e;font-size:12px'

function _section(title) {
  return el('div', {
    text: title,
    attrs: { style: 'font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;color:#8b949e;margin:14px 0 6px' },
  })
}

function _kv(label, value, { strong = false } = {}) {
  const row = el('div', { attrs: { style: 'display:flex;justify-content:space-between;gap:16px;padding:2px 0' } })
  row.append(
    el('span', { text: label, attrs: { style: 'color:#8b949e;font-size:12px' } }),
    el('span', { text: value, attrs: { style: `font-size:12px;font-variant-numeric:tabular-nums;color:${strong ? '#e6edf3' : '#c9d1d9'};${strong ? 'font-weight:600' : ''}` } }),
  )
  return row
}

function _jobRows(jobs) {
  const wrap = el('div')
  if (!jobs.length) {
    wrap.append(el('div', { text: 'none', attrs: { style: _DIM } }))
    return wrap
  }
  for (const j of jobs) {
    const row = el('div', { attrs: { style: 'display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid #21262d' } })
    row.append(
      el('span', { text: j.job_id, attrs: { style: 'font-family:var(--font-mono,monospace);font-size:11px;color:#c9d1d9;flex-shrink:0' } }),
      el('span', { text: j.status ?? '—', attrs: { style: `font-size:11px;color:#8b949e;flex-shrink:0` } }),
      el('span', { text: j.design_name ?? '', attrs: { style: 'font-size:11px;color:#6e7681;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' } }),
      el('span', { text: formatBytes(j.size_bytes), attrs: { style: 'font-size:12px;font-variant-numeric:tabular-nums;color:#d29922;flex-shrink:0' } }),
    )
    row.title = j.design_name ?? ''
    wrap.append(row)
  }
  return wrap
}

function _renderBody(body, d) {
  body.innerHTML = ''

  if (d.empty) {
    body.append(el('div', {
      text: 'No design is open. Open a part to see its bases, loadouts, and simulation data.',
      attrs: { style: _DIM },
    }))
    return
  }

  const head = el('div', { attrs: { style: 'display:flex;justify-content:space-between;align-items:baseline;gap:12px' } })
  head.append(
    el('div', { text: d.name, attrs: { style: 'font-size:14px;font-weight:600;color:#e6edf3' } }),
    el('div', { text: d.path || 'unsaved', attrs: { style: 'font-family:var(--font-mono,monospace);font-size:11px;color:#6e7681' } }),
  )
  body.append(head)

  // ── Topology ──────────────────────────────────────────────────────────────
  body.append(_section('Design'))
  body.append(_kv('Total bases', d.total_bases.toLocaleString()))
  body.append(_kv('Strands', String(d.strand_count)))
  body.append(_kv('Helices', String(d.helix_count)))
  body.append(_kv('Feature-log entries', String(d.feature_log_count)))

  // ── Loadouts ────────────────────────────────────────────────────────────--
  body.append(_section(`Loadouts (${d.loadout_count})`))
  if (!d.loadouts.length) {
    body.append(el('div', {
      text: 'No named loadouts — the active timeline has ' + d.feature_log_count + ' feature' + (d.feature_log_count === 1 ? '' : 's') + '.',
      attrs: { style: _DIM },
    }))
  } else {
    for (const lo of d.loadouts) {
      const fc = lo.feature_count == null ? '—' : `${lo.feature_count} feature${lo.feature_count === 1 ? '' : 's'}`
      body.append(_kv(lo.name + (lo.is_active ? '  (active)' : ''), fc))
    }
  }

  // ── Simulation data on disk ────────────────────────────────────────────────
  body.append(_section(`oxDNA jobs (${d.oxdna_jobs.length}) — ${formatBytes(d.oxdna_total_bytes)}`))
  body.append(_jobRows(d.oxdna_jobs))
  body.append(_section(`MD jobs (${d.md_jobs.length}) — ${formatBytes(d.md_total_bytes)}`))
  body.append(_jobRows(d.md_jobs))

  // ── Assemblies ──────────────────────────────────────────────────────────--
  body.append(_section(`Used in assemblies (${d.assemblies.length})`))
  if (!d.assemblies.length) {
    body.append(el('div', { text: d.path ? 'not used in any assembly' : 'design not yet saved', attrs: { style: _DIM } }))
  } else {
    for (const a of d.assemblies) {
      body.append(el('div', { text: a.path, attrs: { style: 'font-size:12px;color:#c9d1d9;padding:2px 0' } }))
    }
  }

  // ── Disk total ──────────────────────────────────────────────────────────--
  body.append(_section('On disk'))
  body.append(_kv('Design file', formatBytes(d.file_size_bytes)))
  body.append(_kv('Simulation data', formatBytes(d.sim_total_bytes)))
  body.append(_kv('Total', formatBytes(d.total_disk_bytes), { strong: true }))
}

export async function showAboutFileModal({ api, path }) {
  const body = el('div', { attrs: { style: 'min-height:80px' } })
  body.append(el('div', { text: 'Loading…', attrs: { style: _DIM } }))
  const modal = createModal({
    title: 'About this file',
    size: 'lg',
    body,
    actions: [createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() })],
  })
  modal.open()
  try {
    const d = await api.getDesignAbout(path)
    _renderBody(body, d)
  } catch (e) {
    body.innerHTML = ''
    body.append(el('div', { text: `Could not load file details: ${e?.message ?? e}`, attrs: { style: 'color:#f85149;font-size:12px' } }))
  }
}
