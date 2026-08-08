/**
 * Job Wizard step 1 — the SLURM resources for an Alpine run.
 *
 * These five numbers (GPUs, cores, memory, wall time, QoS) used to be collected by a
 * confirmation card that appeared AFTER the job had been created and prepared. That was
 * the wrong moment twice over: the node had already been chosen a whole wizard ago, and
 * the popup pre-empted the panel, so anchors and an electric field — which attach to a
 * prepared job — could not be set before it demanded an answer.
 *
 * So they live here, directly under the partition table, and they arrive ALREADY SIZED
 * for the design that is open: `POST /cluster/slurm-preview` estimates the solvated atom
 * count from the live design and runs the same recommender the submit path uses.
 *
 * What gets sent is only what the user CHANGED. The estimate exists before the package
 * does, so an untouched field is left to the backend, which re-derives it at submit time
 * from the built package's exact atom count. Editing one pins it.
 *
 * Pure shaping (field descriptors, the recommended-vs-edited split, the context rows)
 * lives in `md_job_wizard_target_model.js`; this factory owns DOM and fetch.
 */

import { cleanResourceOverrides, qosSelectOptions } from './md_submit_review.js'
import {
  RESOURCE_FIELDS, resourceContextRows, resourceFieldValues, resourceNotes,
} from './md_job_wizard_target_model.js'

const _esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

const _INPUT_CSS =
  'width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;'
  + 'border-radius:3px;padding:3px 5px;font-size:11px'

/**
 * @param {object}   deps
 * @param {Element}  deps.mount            where the block renders (inside the Alpine card)
 * @param {Function} deps.getSlurmPreview  body => Promise<preview>  (POST /cluster/slurm-preview)
 * @param {Function} deps.getPartition     () => string|null  — the selected partition
 * @param {Function} deps.getTotalNs       () => number — the plan's total simulated ns
 * @param {Function} [deps.onChange]       fired when an edit changes the payload
 * @param {Function} [deps.readOnly]       () => boolean — showing a job that already exists
 * @param {Function} [deps.getRecorded]    () => {resources, requested} — in read-only, what
 *   the job was submitted with (`resources`) and what the user had pinned by hand
 *   (`requested`, the sparse `slurm_resources`). Used instead of re-running the sizing
 *   estimate, which reads the design open NOW and would answer a different question.
 */
export function initWizardResources({
  mount, getSlurmPreview, getPartition = () => null, getTotalNs = () => 0,
  onChange = () => {}, readOnly = () => false, getRecorded = () => null,
} = {}) {
  const _ro = () => !!readOnly()
  let _preview = null
  let _busy = false
  let _error = ''
  let _key = ''            // partition|total_ns — the sizing is only valid for one pair
  // Only what the user typed. Survives a re-size on purpose: an explicit 48 h wall time
  // is a decision about this run, not about the partition that happened to be selected
  // when it was made.
  let _edited = {}

  const _sizedKey = () => `${getPartition() || ''}|${Number(getTotalNs() || 0)}`

  /**
   * Size the request for the selected partition. Cheap to call: it no-ops unless the
   * partition or the run length actually moved, because the atom estimate behind it
   * builds the design's whole heavy-atom model the first time (~26 s on a 6-helix
   * bundle, memoised on the design afterwards).
   */
  async function refresh({ force = false } = {}) {
    if (_ro()) { paint(); return }
    const partition = getPartition()
    if (!partition) { _preview = null; _key = ''; paint(); return }
    const key = _sizedKey()
    if (!force && key === _key && (_preview || _busy)) return
    _key = key
    _busy = true
    _error = ''
    paint()
    try {
      _preview = await getSlurmPreview?.({
        cluster_name: 'alpine', partition, total_ns: Number(getTotalNs() || 0),
        job_name: 'nadoc_job',
      })
      if (!_preview) _error = 'Could not size this run on the cluster.'
      else if (_preview.sized === false) _error = _preview.reason || 'Not sized.'
    } catch (err) {
      _preview = null
      _error = `Could not size this run: ${err?.message || err}`
    } finally {
      _busy = false
      paint()
      onChange()
    }
  }

  function _rowHtml(label, value) {
    return (
      '<div style="display:flex;justify-content:space-between;gap:12px;padding:1px 0">'
      + `<span style="color:#6e7681">${_esc(label)}</span>`
      + `<span style="color:#c9d1d9;text-align:right">${_esc(value)}</span></div>`
    )
  }

  function _fieldHtml(field, shown) {
    const chip = shown.edited
      ? '<span style="color:#58a6ff;font-size:9px">you set this</span>'
      : (shown.recommended !== ''
        ? '<span style="color:#6e7681;font-size:9px">recommended</span>'
        : '')
    const label =
      `<div style="display:flex;align-items:baseline;gap:6px;margin-bottom:2px">`
      + `<span style="color:#8b949e;font-size:11px">${_esc(field.label)}`
      + `${field.unit ? ` <span style="color:#6e7681">(${_esc(field.unit)})</span>` : ''}</span>`
      + chip + '</div>'
    if (field.type === 'select') {
      const opts = qosSelectOptions(_preview)
        .map(o => `<option value="${_esc(o.value)}"${o.value === shown.value ? ' selected' : ''}>`
          + `${_esc(o.label)}</option>`).join('')
      return label
        + `<select data-res="${field.key}" style="${_INPUT_CSS}">${opts}</select>`
    }
    return label
      + `<input data-res="${field.key}" type="${field.type}" value="${_esc(shown.value)}"`
      + (field.min != null ? ` min="${field.min}"` : '')
      + (field.step != null ? ` step="${field.step}"` : '')
      + (field.placeholder ? ` placeholder="${_esc(field.placeholder)}"` : '')
      + ` style="${_INPUT_CSS}">`
  }

  function paint() {
    if (!mount) return
    if (_ro()) { _paintRecorded(); return }
    const partition = getPartition()
    if (!partition) {
      mount.innerHTML =
        '<div style="font-size:11px;color:#6e7681;padding:8px 0">'
        + 'Pick a node above to size this run.</div>'
      return
    }
    const head =
      '<div style="display:flex;align-items:baseline;gap:8px;margin:12px 0 6px">'
      + '<span style="font-size:12px;color:#c9d1d9;font-weight:600">Resources on '
      + `${_esc(partition)}</span>`
      + (_edited && Object.keys(_edited).length
        ? '<button type="button" id="wiz-res-reset" style="background:none;border:0;'
          + 'color:#58a6ff;cursor:pointer;padding:0;font-size:10px">reset to recommended</button>'
        : '')
      + '</div>'

    if (_busy) {
      mount.innerHTML = head
        + '<div style="font-size:11px;color:#8b949e;padding:4px 0">'
        + 'Sizing this design for the cluster…</div>'
      return
    }
    if (_error || !_preview?.resources) {
      mount.innerHTML = head
        + '<div style="font-size:11px;color:#d29922;padding:4px 0">'
        + `${_esc(_error || 'Not sized yet.')} Wall time and cores fall back to the `
        + 'automatic recommendation made when the job is submitted.</div>'
      _wire()
      return
    }

    const shown = resourceFieldValues(_preview, _edited)
    const fields = RESOURCE_FIELDS
      .map(f => `<div>${_fieldHtml(f, shown[f.key])}</div>`).join('')
    const notes = resourceNotes(_preview)
    mount.innerHTML = head
      + '<div style="font-size:11px;margin-bottom:8px">'
      + resourceContextRows(_preview).map(([k, v]) => _rowHtml(k, v)).join('')
      + '</div>'
      + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">'
      + fields + '</div>'
      + (notes.length
        ? `<div style="font-size:10px;color:#6e7681;margin-top:8px;line-height:1.5">${
          notes.map(n => `• ${_esc(n)}`).join('<br>')}</div>`
        : '')
      + '<div style="font-size:10px;color:#6e7681;margin-top:6px;line-height:1.5">'
      + 'Sized from this design before it is solvated. Anything you leave alone is '
      + 're-derived from the finished package’s exact atom count when the job is '
      + 'submitted; anything you change is used as typed.</div>'
    _wire()
  }

  /**
   * The locked block: the SLURM request this job was actually submitted with.
   *
   * `resources` is what the submit path resolved (and what SLURM was asked for);
   * `requested` is the sparse set the user pinned by hand in the wizard, so the chips keep
   * saying which numbers were a decision and which were the recommendation. Everything is
   * a disabled text box — including QoS, which is a select in the live block only because
   * the live block has a list of valid tiers to offer.
   */
  function _paintRecorded() {
    const rec = getRecorded() || {}
    const resources = rec.resources || null
    const shown = resourceFieldValues({ resources }, rec.requested || {})
    const head =
      '<div style="display:flex;align-items:baseline;gap:8px;margin:12px 0 6px">'
      + '<span style="font-size:12px;color:#c9d1d9;font-weight:600">Resources requested'
      + `${getPartition() ? ` on ${_esc(getPartition())}` : ''}</span></div>`
    if (!resources) {
      mount.innerHTML = head
        + '<div style="font-size:11px;color:#8b949e;padding:4px 0">'
        + 'This job was never submitted to the cluster, so no SLURM request was resolved.'
        + (Object.keys(rec.requested || {}).length
          ? ' The values pinned in the wizard were: '
            + _esc(Object.entries(rec.requested).map(([k, v]) => `${k} ${v}`).join(', ')) + '.'
          : '')
        + '</div>'
      return
    }
    const fields = RESOURCE_FIELDS.map(f => {
      const s = shown[f.key]
      const chip = s.edited
        ? '<span style="color:#58a6ff;font-size:9px">you set this</span>'
        : '<span style="color:#6e7681;font-size:9px">recommended</span>'
      return '<div><div style="display:flex;align-items:baseline;gap:6px;margin-bottom:2px">'
        + `<span style="color:#8b949e;font-size:11px">${_esc(f.label)}`
        + `${f.unit ? ` <span style="color:#6e7681">(${_esc(f.unit)})</span>` : ''}</span>`
        + chip + '</div>'
        + `<input type="text" value="${_esc(s.value)}" disabled style="${_INPUT_CSS}"></div>`
    }).join('')
    const notes = resourceNotes({ resources })
    mount.innerHTML = head
      + '<div style="font-size:11px;margin-bottom:8px">'
      + resourceContextRows({ resources }).map(([k, v]) => _rowHtml(k, v)).join('')
      + '</div>'
      + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">'
      + fields + '</div>'
      + (notes.length
        ? `<div style="font-size:10px;color:#6e7681;margin-top:8px;line-height:1.5">${
          notes.map(n => `• ${_esc(n)}`).join('<br>')}</div>`
        : '')
  }

  function _wire() {
    mount.querySelector('#wiz-res-reset')?.addEventListener('click', () => {
      _edited = {}
      paint()
      onChange()
    })
    mount.querySelectorAll('[data-res]').forEach(node => {
      const key = node.dataset.res
      const record = () => {
        const v = String(node.value ?? '').trim()
        if (v === '') delete _edited[key]
        else _edited[key] = v
        onChange()
      }
      // `input` keeps the payload current mid-typing without touching the DOM (a repaint
      // there would steal focus); `change` (blur / a select's pick) is when the chips and
      // the reset link are allowed to catch up.
      node.addEventListener('input', record)
      node.addEventListener('change', () => { record(); paint() })
    })
  }

  return {
    render: paint,
    refresh,
    /** The sparse `slurm_resources` for the create request — only what was edited. */
    overrides: () => cleanResourceOverrides(_edited),
    /** The sizing currently on screen (null until a partition is picked). */
    preview: () => _preview,
    reset() { _edited = {}; _preview = null; _key = ''; paint() },
  }
}
