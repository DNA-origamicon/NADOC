import '../styles/oxdna_torsion.css'
import { addAnchors, anchorKey, makeAnchorLabeller, resolveSelectionAnchors } from '../scene/efield_math.js'
import { el } from './primitives/dom.js'
import { createButton } from './primitives/button.js'
import { downloadHref, downloadText, openMetricExportModal } from './metric_export_modal.js'

const modes = { rotation: 'Rotation ramp', tangential: 'Tangential load' }
export const DEFAULT_TORQUE_ARROW_SIZE = 100
const fmt = (value, units = '') => value == null ? '—' : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}${units ? ` ${units}` : ''}`

function field(label, control) {
  return el('label', { children: [el('span', { text: label }), control] })
}

function number(value, step = 'any') {
  return el('input', { attrs: { type: 'number', value, step } })
}

function select(entries) {
  return el('select', { children: Object.entries(entries).map(([value, name]) => el('option', { attrs: { value }, text: name })) })
}

const channels = {
  applied: ['applied_torque_pn_nm', '#5cc8e6'],
  reaction: ['clamp_reaction_pn_nm', '#e8ae68'],
}

function drawCurve(canvas, rows, trace, angle, axisLabel) {
  const ctx = canvas.getContext('2d')
  const valid = rows.filter(r => r[angle] != null)
  if (!ctx || !valid.length) return
  const { width, height } = canvas
  const plot = { left: 55, right: width - 10, top: 18, bottom: height - 26 }
  const xs = valid.map(r => r[angle])
  const series = (trace === 'both' ? Object.values(channels) : [channels[trace]])
    .filter(([key]) => valid.some(row => row[key] != null))
  const ys = valid.flatMap(r => series.map(([key]) => r[key]))
  const xmin = Math.min(0, ...xs), xmax = Math.max(0, ...xs)
  const ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys)
  const x = v => plot.left + (plot.right - plot.left) * (v - xmin) / (xmax - xmin || 1)
  const y = v => plot.bottom - (plot.bottom - plot.top) * (v - ymin) / (ymax - ymin || 1)
  ctx.fillStyle = '#0d1117'
  ctx.fillRect(0, 0, width, height)
  ctx.fillStyle = '#a3afbd'
  ctx.font = '11px system-ui'
  ctx.fillText('pN·nm', 3, 11)
  ctx.fillText(axisLabel, plot.right - ctx.measureText(axisLabel).width, height - 3)
  ctx.strokeStyle = '#384452'
  ctx.beginPath()
  ctx.moveTo(plot.left, plot.top)
  ctx.lineTo(plot.left, plot.bottom)
  ctx.lineTo(plot.right, plot.bottom)
  ctx.stroke()
  const tick = n => Math.abs(n) >= 1000 ? n.toExponential(1) : fmt(n)
  ctx.fillText(tick(ymax), 3, plot.top + 5)
  if (ymax !== ymin) ctx.fillText(tick(ymin), 3, plot.bottom)
  ctx.fillText(fmt(xmin), plot.left, height - 12)
  if (xmax !== xmin) ctx.fillText(fmt(xmax), plot.right - 30, height - 12)
  for (const [key, color] of series) {
    ctx.strokeStyle = color
    ctx.lineWidth = 1.6
    ctx.beginPath()
    valid.filter(row => row[key] != null).forEach((r, i) => (i ? ctx.lineTo(x(r[angle]), y(r[key])) : ctx.moveTo(x(r[angle]), y(r[key]))))
    ctx.stroke()
    if (valid.length === 1) {
      ctx.fillStyle = color
      ctx.fillRect(x(xs[0]) - 2, y(valid[0][key]) - 2, 4, 4)
    }
  }
}

function exportRows(rows) {
  const columns = Object.keys(rows[0])
  const csv = [columns.join(','), ...rows.map(row => columns.map(k => row[k] ?? '').join(','))].join('\n')
  downloadText('nadoc-torque.csv', csv)
}

export function fitTorsionalStiffness(rows, min, max) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) return null
  const points = rows.filter(r => r.twist_deg != null && r.twist_deg >= min && r.twist_deg <= max)
  if (new Set(points.map(r => r.twist_deg)).size < 3) return null
  const x = points.map(r => r.twist_deg * Math.PI / 180)
  const y = points.map(r => r.clamp_reaction_pn_nm)
  const avg = values => values.reduce((sum, n) => sum + n, 0) / values.length
  const xc = avg(x), yc = avg(y)
  const xx = x.reduce((sum, n) => sum + (n - xc) ** 2, 0)
  const yy = y.reduce((sum, n) => sum + (n - yc) ** 2, 0)
  const xy = x.reduce((sum, n, i) => sum + (n - xc) * (y[i] - yc), 0)
  return xx > 0 ? { slope: xy / xx, r2: yy > 0 ? xy ** 2 / (xx * yy) : null, samples: points.length } : null
}

function stiffnessControl(rows) {
  const from = number(''), to = number('')
  const status = el('p', { attrs: { role: 'status' } })
  const fit = createButton({ label: 'Fit stiffness', size: 'sm' })
  fit.addEventListener('click', () => {
    const result = fitTorsionalStiffness(rows, from.valueAsNumber, to.valueAsNumber)
    status.textContent = result
      ? `Apparent stiffness ${fmt(result.slope, 'pN·nm/rad')} · R² ${fmt(result.r2)} · ${result.samples} samples`
      : 'Choose an increasing twist range with at least three samples at distinct angles.'
  })
  return el('details', { children: [el('summary', { text: 'Fit torsional stiffness' }),
    el('div', { className: 'oxdna-torsion-grid', children: [field('From twist (°)', from), field('To twist (°)', to)] }), fit, status] })
}

function renderResults(container, result) {
  const last = result.rows.at(-1)
  const relative = result.fixture.clamp_particles && result.rows.some(row => row.twist_deg != null)
  const angle = relative ? 'twist_deg' : 'drive_rotation_deg'
  const axisLabel = relative ? 'Relative twist' : 'Drive rotation'
  const table = el('dl', { className: 'oxdna-torsion-values' })
  for (const [label, value] of [
    [axisLabel, fmt(last[angle], '°')],
    ['Peak clamp reaction', fmt(result.peak_clamp_reaction_pn_nm, 'pN·nm')],
    ['Late applied torque', fmt(result.late_mean_applied_pn_nm, 'pN·nm')],
    ['Late clamp reaction', fmt(result.late_mean_reaction_pn_nm, 'pN·nm')],
    ['Reaction / applied', fmt(result.late_reaction_to_applied)],
    ['Maximum clamp motion', fmt(result.max_clamp_displacement_nm, 'nm')],
    ['Backbone bonds past FENE limit', fmt(result.max_backbone_over_limit)],
  ]) table.append(el('dt', { text: label }), el('dd', { text: value }))
  const chart = el('canvas', { attrs: { width: 310, height: 190, role: 'img', 'aria-label': 'Torque versus ' + axisLabel.toLowerCase() } })
  const trace = select(result.fixture.clamp_particles
    ? { both: 'Applied and reaction', reaction: 'Clamp reaction', applied: 'Applied torque' }
    : { applied: 'Applied torque' })
  const key = el('div', { className: 'oxdna-torsion-key', children: [
    el('span', { text: 'Applied' }), el('span', { text: 'Clamp reaction' }),
  ] })
  const paint = () => {
    key.children[0].hidden = trace.value === 'reaction'
    key.children[1].hidden = trace.value === 'applied'
    drawCurve(chart, result.rows, trace.value, angle, axisLabel + ' (°)')
  }
  trace.addEventListener('change', paint)
  const losses = result.pairing_loss.filter(row => row.lost > 0)
  const bond = result.most_stretched_backbone_bond
  const failure = el('details', { children: [
    el('summary', { text: 'Failure indicators' }),
    ...(bond ? [el('p', { text: `Longest backbone bond ${fmt(bond.length_nm, 'nm')} at step ${fmt(bond.step)}. ${bond.from} → ${bond.to}.` })] : []),
    el('p', { text: `Peak loss of paired geometry at step ${fmt(result.peak_pair_loss_step)}.` }),
    el('p', { text: 'Counts use initially paired base sites and a 0.8 nm separation threshold.' }),
    ...(losses.length ? losses.map(row => el('div', { text: `${row.group} · ${row.lost} of ${row.initially_paired}` }))
      : [el('p', { text: 'All initially paired sites remained within the threshold in the sampled frames.' })]),
  ] })
  container.replaceChildren(
    ...(result.job_error ? [el('p', { className: 'oxdna-torsion-error', text: result.job_error })] : []),
    el('p', { text: `${result.rows.length} sampled frames · from step ${fmt(result.latest_attempt_from_step)}. Late means use the last ${result.late_window_samples} samples.` }),
    field('Torque–rotation plot', trace), chart, key, table,
    ...(relative ? [stiffnessControl(result.rows)] : []), failure,
  )
  paint()
  return chart
}

export function initOxdnaTorque({ mount, gizmo, getSelection, getSelectionCenter, getDefaultCenter, onChange }) {
  if (!mount) return { apply() {}, refresh() {}, settings: () => null, arrowSize: () => DEFAULT_TORQUE_ARROW_SIZE, valid: () => true }
  let jobId = null, axis = null, drive = [], editable = false, visible = true, engine = 'oxdna'
  let legacy = null
  const enabled = el('input', { attrs: { type: 'checkbox' } })
  const mode = select(modes)
  const target = number('10')
  const targetLabel = el('span')
  const driveStiffness = number('5')
  const modeField = field('Control mode', mode)
  const stiffnessField = field('Drive stiffness (oxDNA units)', driveStiffness)
  const position = ['X', 'Y', 'Z'].map(() => number('0'))
  const rotation = ['X', 'Y', 'Z'].map(() => number('0'))
  const status = el('p', { attrs: { role: 'status' } })
  const driveList = el('div', { className: 'oxdna-torsion-sites' })
  const add = createButton({ label: 'Add selection to drive', size: 'sm' })
  const center = createButton({ label: 'Center on Selection', size: 'sm' })
  const editAxis = createButton({ label: 'Select axis in viewport', size: 'sm' })
  const size = el('input', { attrs: { type: 'range', min: 50, max: 300, step: 1, value: DEFAULT_TORQUE_ARROW_SIZE,
    'aria-label': 'Arrow size' } })
  const sizeValue = el('output')
  const sizeField = el('label', { className: 'oxdna-torque-arrow-size', children: [
    el('span', { text: 'Arrow size' }), sizeValue, size,
  ] })
  const vector = (legend, prefix, fields) => el('fieldset', { children: [
    el('legend', { text: legend }),
    el('div', { className: 'oxdna-torsion-vector', children: fields.map((input, i) => {
      const name = 'XYZ'[i]
      input.setAttribute('aria-label', prefix + ' ' + name)
      return field(name, input)
    }) }),
  ] })
  const axisFields = el('details', { className: 'oxdna-torsion-coordinates', children: [
    el('summary', { text: 'Position and rotation' }),
    vector('Position (nm)', 'Axis position', position), vector('Rotation (°)', 'Axis rotation', rotation),
  ] })
  const setup = el('div', { className: 'oxdna-torsion-setup', children: [
    modeField, el('label', { children: [targetLabel, target] }), stiffnessField,
    el('div', { className: 'oxdna-torsion-grip', children: [el('strong', { text: 'Driven sites' }), add, driveList] }),
    el('strong', { text: 'Axis of Rotation' }), sizeField, editAxis,
    el('p', { text: 'Select the arrow and press Tab to switch between move and rotate.' }),
    axisFields, center,
  ] })
  const enableLabel = el('label', { className: 'oxdna-torque-enable', children: [
    enabled, el('span', { text: 'Apply torque' }),
  ] })
  mount.append(el('summary', { className: 'ox-card__header', children: [
    el('span', { className: 'ox-card__chevron icon icon--xs icon--rotates',
      attrs: { 'data-icon': 'chevron-down', 'aria-hidden': 'true' } }),
    el('span', { className: 'ox-card__title', text: 'Torque' }),
  ] }), el('div', { className: 'ox-card__body oxdna-torsion', children: [enableLabel, setup, status] }))

  function defaultAxis() {
    return { kind: 'pose', position_nm: getDefaultCenter?.() || [0, 0, 0], rotation_deg: [0, 0, 0] }
  }
  function setAxis(value, updateInputs = true, updateViewport = true) {
    axis = value
    if (updateInputs) {
      position.forEach((input, i) => { input.value = String(value.position_nm[i]) })
      rotation.forEach((input, i) => { input.value = String(value.rotation_deg[i]) })
    }
    if (updateViewport) gizmo?.setPose(value)
  }
  function paintDrive() {
    const design = getSelection?.()?.currentDesign
    const label = makeAnchorLabeller(design)
    const names = new Map((design?.cluster_transforms || []).map(c => [c.id, c.name]))
    driveList.replaceChildren(...drive.map(ref => {
      const name = (ref.kind === 'cluster' ? names.get(ref.id) : null) || label(ref)
      const remove = createButton({ label: '×', size: 'sm' })
      remove.disabled = !editable
      remove.setAttribute('aria-label', 'Remove ' + name + ' from drive')
      remove.addEventListener('click', () => {
        drive = drive.filter(r => anchorKey(r) !== anchorKey(ref))
        paintDrive()
        commit()
      })
      return el('div', { children: [el('span', { text: name }), remove] })
    }))
    if (!drive.length) driveList.textContent = 'All unanchored particles'
  }
  function paint() {
    enabled.disabled = !editable
    setup.hidden = !enabled.checked || !editable
    targetLabel.textContent = mode.value === 'rotation' ? 'Grip rotation (°)' : 'Nominal torque (pN·nm)'
    stiffnessField.hidden = mode.value !== 'rotation'
    gizmo?.show(visible && engine === 'oxdna' && mount.open && !setup.hidden)
  }
  function paintSize() {
    sizeValue.value = size.value + '%'
    gizmo?.setSize?.(size.valueAsNumber)
  }
  function selectAxis() {
    paint()
    gizmo?.select()
  }
  function valid() {
    return !enabled.checked || (Number.isFinite(target.valueAsNumber)
      && Number.isFinite(driveStiffness.valueAsNumber) && driveStiffness.valueAsNumber > 0
      && [...position, ...rotation].every(input => Number.isFinite(input.valueAsNumber)))
  }
  function settings() {
    if (!enabled.checked) return null
    if (legacy) return legacy
    return { mode: mode.value, target: target.valueAsNumber, axis, drive, drive_stiffness: driveStiffness.valueAsNumber }
  }
  function commit() {
    legacy = null
    status.textContent = valid() ? '' : 'Enter finite axis, load and stiffness values.'
    if (valid()) onChange?.()
  }
  enabled.addEventListener('change', () => {
    if (enabled.checked && !axis) setAxis(defaultAxis())
    paint()
    commit()
  })
  mode.addEventListener('change', () => {
    target.value = mode.value === 'rotation' ? '10' : '50'
    if (!(driveStiffness.valueAsNumber > 0)) driveStiffness.value = '5'
    paint()
    commit()
  })
  for (const input of [target, driveStiffness]) input.addEventListener('input', commit)
  size.addEventListener('input', () => {
    paintSize()
    selectAxis()
    if (valid()) onChange?.()
  })
  for (const input of [...position, ...rotation]) input.addEventListener('input', () => {
    if ([...position, ...rotation].every(n => Number.isFinite(n.valueAsNumber))) setAxis({ kind: 'pose', position_nm: position.map(n => n.valueAsNumber),
      rotation_deg: rotation.map(n => n.valueAsNumber) }, false)
    selectAxis()
    commit()
  })
  gizmo?.setOnChange(value => {
    if (!editable || !enabled.checked) return
    setAxis(value, true, false)
    commit()
  })
  center.addEventListener('click', () => {
    const point = getSelectionCenter?.()
    if (!point) { status.textContent = 'Select one or more elements in the viewport.'; return }
    setAxis({ ...axis, position_nm: point })
    selectAxis()
    commit()
  })
  editAxis.addEventListener('click', selectAxis)
  axisFields.addEventListener('toggle', () => {
    if (axisFields.open) selectAxis()
  })
  add.addEventListener('click', () => {
    const picked = resolveSelectionAnchors(getSelection?.())
    if (!picked.length) { status.textContent = 'Select bases, domains, strands or clusters to drive.'; return }
    drive = addAnchors(drive, picked)
    paintDrive()
    commit()
  })
  mount.addEventListener('toggle', paint)
  window.addEventListener('nadoc:left-tab-change', ({ detail }) => {
    visible = (detail?.openPanels?.includes('dynamics') ?? detail?.activeTab === 'dynamics') && !detail?.collapsed
    paint()
  })
  window.addEventListener('nadoc:simulation-engine', ({ detail }) => { engine = detail.engine; paint() })

  function refresh(job, canEdit) {
    editable = canEdit
    if (!editable || job?.job_id !== jobId) {
      status.textContent = job?.run_config?.torsion
        ? 'See Graphs and Metrics for this run.'
        : 'Create and select a local production job to set up torque.'
    }
    paint()
  }
  function apply(job, canEdit) {
    const config = job?.run_config?.torsion
    const savedAxis = config?.axis?.kind === 'pose' ? config.axis : null
    const sameJob = jobId === job?.job_id
    jobId = job?.job_id ?? null
    editable = canEdit
    legacy = config && !savedAxis ? config : null
    enabled.checked = !!config
    mode.value = config?.mode || 'rotation'
    target.value = String(config?.target ?? 10)
    driveStiffness.value = String(config?.drive_stiffness ?? 5)
    size.value = String(job?.run_config?.torque_arrow_size ?? DEFAULT_TORQUE_ARROW_SIZE)
    paintSize()
    drive = config?.drive || []
    if (savedAxis || !sameJob || !axis) setAxis(savedAxis || defaultAxis())
    paintDrive()
    status.textContent = ''
    refresh(job, canEdit)
  }
  paintSize()
  paint()
  return { apply, refresh, settings, arrowSize: () => size.valueAsNumber, valid }
}

/** Result generation follows the same Generate / Display / Export flow as the other metrics. */
export function initTorqueMetrics({ mount, getJob, result, lastError }) {
  if (!mount) return { refresh() {} }
  const generate = mount.querySelector('[data-torque-generate]')
  const display = mount.querySelector('[data-torque-display]')
  const download = mount.querySelector('[data-torque-export]')
  const status = mount.querySelector('[role=status]')
  const output = mount.querySelector('[data-torque-output]')
  let selected = null
  let pending = null
  const cached = new Map()
  function refresh() {
    const job = getJob?.()
    const id = job?.job_id ?? null
    if (selected !== id) {
      selected = id
      output.replaceChildren()
      status.textContent = ''
    }
    mount.hidden = !job?.run_config?.torsion
    generate.disabled = !['completed', 'stopped', 'failed'].includes(job?.status) || pending === id
    display.disabled = download.disabled = !cached.has(id)
  }
  generate.addEventListener('click', async () => {
    const id = selected
    pending = id
    status.textContent = 'Generating…'
    refresh()
    try {
      const data = await result(id)
      if (!data) throw new Error(lastError?.() || 'Could not generate torque metrics.')
      cached.set(id, data)
      if (selected === id) {
        output.replaceChildren()
        status.textContent = data.rows.length + ' sampled frames'
      }
    } catch (error) {
      if (selected === id) status.textContent = error.message
    } finally {
      if (pending === id) pending = null
      refresh()
    }
  })
  display.addEventListener('click', () => {
    if (output.childElementCount) output.replaceChildren()
    else renderResults(output, cached.get(selected))
  })
  download.addEventListener('click', async () => {
    const jobId = selected
    const data = cached.get(jobId)
    const choice = await openMetricExportModal()
    if (choice?.png) {
      const displayed = jobId === selected ? output.querySelector('canvas') : null
      const chart = displayed || renderResults(el('div'), data)
      downloadHref('nadoc-torque.png', chart.toDataURL('image/png'))
    }
    if (choice?.data) exportRows(data.rows)
  })
  refresh()
  return { refresh }
}
