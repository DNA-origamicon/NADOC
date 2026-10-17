import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { toolSection } from './tool_sections.js'
import { cloneRepairInput } from '../features/part_repair_model.js'

// This is an ordinary input editor, gated until the complete workflow is qualified.
export const ROUTING_HISTORY_EDITOR_ENABLED = false
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key)
const scalar = (key, label, type, options = {}) => ({ key, label, type, ...options })
const id = (key, label, resource) => scalar(key, label, 'id', { resource })
const integer = (key, label) => scalar(key, label, 'integer')
const direction = (key = 'direction', label = 'Direction') => scalar(key, label, 'choice', { choices: ['FORWARD', 'REVERSE'] })
const helix = id('helix_id', 'Helix ID', 'helices')
const crossover = id('crossover_id', 'Crossover ID', 'crossovers')
const forced = id('fl_id', 'Forced ligation ID', 'forced_ligations')
const sequence = scalar('sequence', 'Sequence', 'sequence')
const site = [helix, integer('bp_index', 'Base index'), direction()]
const half = [helix, integer('index', 'Index'), direction('strand')]
const placement = [scalar('half_a', 'Half A', 'object', { fields: half }), scalar('half_b', 'Half B', 'object', { fields: half }),
  integer('nick_bp_a', 'Nick A (bp)'), integer('nick_bp_b', 'Nick B (bp)'), scalar('process_id', 'Process ID', 'nullable', { optional: true, fallback: 'manual' })]
const move = [crossover, integer('new_index', 'New index')]
const list = (key, label, fields, defaults) => scalar(key, label, 'list', { fields, defaults })
const ids = (key, label, resource) => list(key, label, [id('$value', 'ID', resource)], () => '')
const planes = [ids('helix_ids', 'Helix', 'helices'), integer('plane_a_bp', 'Start plane (bp)'), integer('plane_b_bp', 'End plane (bp)')]
const newSite = () => ({ helix_id: '', bp_index: 0, direction: 'FORWARD' })
const newPlacement = () => ({ half_a: { helix_id: '', index: 0, strand: 'FORWARD' }, half_b: { helix_id: '', index: 0, strand: 'REVERSE' },
  nick_bp_a: 0, nick_bp_b: 0, process_id: 'manual' })
const definitions = Object.freeze({
  'strand-end-resize': ['Resize strand ends', [list('entries', 'Entry', [id('strand_id', 'Strand ID', 'strands'), helix,
    scalar('end', 'End', 'choice', { choices: ['5p', '3p'] }), integer('delta_bp', 'Delta (bp)')], () => ({ strand_id: '', helix_id: '', end: '3p', delta_bp: 0 }))]],
  'domain-shift': ['Shift domains', [list('entries', 'Entry', [id('strand_id', 'Strand ID', 'strands'), scalar('domain_index', 'Domain index', 'integer', { minimum: 0 }), integer('delta_bp', 'Delta (bp)')], () => ({ strand_id: '', domain_index: 0, delta_bp: 0 }))]],
  nick: ['Nick', site], 'nick-batch': ['Nick batch', [list('nicks', 'Nick', site, newSite)]], ligate: ['Ligate', site],
  'forced-ligation-create': ['Create forced ligation', [id('three_prime_strand_id', '3′ strand ID', 'strands'), id('five_prime_strand_id', '5′ strand ID', 'strands'), scalar('is_periodic_seam', 'Periodic seam', 'boolean', { optional: true, fallback: false })]],
  'forced-ligation-delete': ['Delete forced ligation', [forced]],
  'forced-ligation-delete-batch': ['Delete forced ligations', [ids('forced_ligation_ids', 'Forced ligation', 'forced_ligations')]],
  'forced-ligation-extra-bases': ['Forced ligation extra bases', [forced, sequence]],
  'crossover-place': ['Place crossover', placement],
  'crossover-place-batch': ['Place crossovers', [list('placements', 'Placement', placement, newPlacement)]],
  'crossover-move': ['Move crossover', move], 'crossover-move-batch': ['Move crossovers', [list('moves', 'Move', move, () => ({ crossover_id: '', new_index: 0 }))]],
  'crossover-delete': ['Delete crossover', [crossover]], 'crossover-delete-batch': ['Delete crossovers', [ids('crossover_ids', 'Crossover', 'crossovers')]],
  'crossover-extra-bases': ['Crossover extra bases', [crossover, sequence]],
  'crossover-extra-bases-batch': ['Crossover extra bases batch', [list('entries', 'Entry', [crossover, sequence], () => ({ crossover_id: '', sequence: '' }))]],
  'loop-skip-insert': ['Insert loop or skip', [helix, integer('bp_index', 'Base index'), scalar('delta', 'Loop/skip change', 'choice', { choices: [-1, 0, 1] })]],
  'loop-skip-twist': ['Loop/skip twist', [...planes, scalar('target_twist_deg', 'Target twist (degrees)', 'number')]],
  'loop-skip-bend': ['Loop/skip bend', [...planes, scalar('radius_nm', 'Radius (nm)', 'number', { positive: true }), scalar('direction_deg', 'Direction (degrees)', 'number', { optional: true, fallback: 0 })]],
  'loop-skip-clear': ['Clear loops and skips in range', planes], 'loop-skip-clear-all': ['Clear all loops and skips', []],
})

/** UI eligibility; full native input proof and reference validation stay on the server. */
export function isNativeRoutingChild(parent, child) {
  return parent?.feature_type === 'routing-cluster' && typeof parent.id === 'string' && !!parent.id
    && child?.feature_type === 'minor' && typeof child.id === 'string' && !!child.id
    && own(definitions, child.op_subtype) && child.params?._proof_version === 1
    && !own(child.params, '_generator') && !own(child.params, '_generated_scope')
}

function cloneInput(value) {
  // Reuse the existing finite JSON operation budget (10k nodes / 256k bytes),
  // without using the repair workflow or cloning the prefix reference catalog.
  try { return cloneRepairInput(value) } catch (error) { throw new Error(error.message.replaceAll('Repair', 'Routing').replaceAll('repair', 'routing')) }
}
const metadata = kind => ['_proof_version', ...(kind === 'forced-ligation-create' ? ['_fl_id'] : []), ...(kind === 'crossover-place' ? ['crossover_id'] : [])]
function checkShape(value, fields, extra = []) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) throw new Error('Unsupported routing input object.')
  const allowed = new Set([...fields.map(field => field.key), ...extra])
  if (Object.keys(value).some(key => !allowed.has(key))) throw new Error('This saved routing definition has unsupported input fields.')
  for (const field of fields) {
    const item = value[field.key]
    if (item === undefined && field.optional) continue
    if (field.type === 'object') checkShape(item, field.fields)
    if (field.type === 'list') {
      if (!Array.isArray(item)) throw new Error(`${field.label} needs an ordered list.`)
      if (field.fields[0].key !== '$value') for (const row of item) checkShape(row, field.fields, field.key === 'placements' ? ['crossover_id'] : [])
    }
  }
}
function draftInputs(packet) {
  if (!own(definitions, packet?.kind) || packet?.params?._proof_version !== 1) throw new Error('This child has no supported native routing input contract.')
  const values = cloneInput(packet.params)
  checkShape(values, definitions[packet.kind][1], metadata(packet.kind))
  return values
}
function validate(value, fields, prefix = '') {
  for (const field of fields) {
    const item = field.key === '$value' ? value.$value : value[field.key], label = prefix + field.label
    if (item === undefined && field.optional) continue
    if (field.type === 'object') { validate(item, field.fields, `${label} `); continue }
    if (field.type === 'list') {
      item.forEach((row, i) => validate(field.fields[0].key === '$value' ? { $value: row } : row, field.fields, `${label} ${i + 1} `)); continue
    }
    if ((field.type === 'integer' && !Number.isSafeInteger(item)) || (field.type === 'number' && !Number.isFinite(item))) throw new Error(`${label} needs a finite ${field.type}.`)
    if ((field.minimum != null && item < field.minimum) || (field.positive && item <= 0)) throw new Error(`${label} is outside its allowed range.`)
    if (field.type === 'choice' && !field.choices.includes(item)) throw new Error(`Choose ${label}.`)
    if (field.type === 'boolean' && typeof item !== 'boolean') throw new Error(`${label} needs a checkbox value.`)
    if (field.type === 'id' && (typeof item !== 'string' || !item.trim())) throw new Error(`Specify ${label}.`)
    if (field.type === 'nullable' && item !== null && typeof item !== 'string') throw new Error(`${label} needs text or null.`)
    if (field.type === 'sequence' && (typeof item !== 'string' || !/^[ACGTNacgtn]*$/.test(item))) throw new Error(`${label} only accepts A, C, G, T or N; leave it empty to clear.`)
  }
}

/** Local authoring inputs only. Prefix choices belong to the selected child. */
export function editRoutingFeature(packet, { onSave, isCurrent = () => true } = {}) {
  const kind = packet?.kind
  let values
  try { values = draftInputs(packet) } catch (error) { return Promise.reject(error) }
  return new Promise(resolve => {
    const [title, fields] = definitions[kind], empty = kind === 'loop-skip-clear-all'
    let saving = false, settled = false, retired = false
    const body = el('div'), form = el('div'), error = el('p', { className: 'tool-help', attrs: { role: 'alert' } })
    error.hidden = true
    const fail = message => { error.textContent = message; error.hidden = false }
    const finish = value => { if (settled) return; settled = true; window.removeEventListener('nadoc:document-reset', reset); resolve(value) }
    const reset = () => { retired = true; modal.close() }
    body.append(el('p', { className: 'tool-help', text: 'Edit this routing step using references from immediately before it. Apply rebuilds later steps; changes here do not modify the part until accepted.' }))
    const catalogs = new Map()
    for (const resource of ['helices', 'strands', 'crossovers', 'forced_ligations']) {
      const listId = `routing-${resource}-${crypto.randomUUID()}`
      const options = (packet.prefix?.[resource] ?? []).map(row => el('option', { attrs: { value: row.id } }))
      catalogs.set(resource, listId); body.append(el('datalist', { id: listId, children: options }))
    }
    const strands = new Map((packet.prefix?.strands ?? []).map(strand => [strand.id, strand]))
    const output = (label, value) => el('p', { className: 'tool-help', children: [`${label}: `, el('output', { attrs: { 'aria-label': label }, text: value ?? 'Assigned when this edit is accepted' })] })
    if (kind === 'crossover-place') body.append(output('Output crossover ID', values.crossover_id))
    if (kind === 'forced-ligation-create') body.append(output('Output forced ligation ID', values._fl_id))
    function controls(target, descriptors, prefix = '', changed = () => {}) {
      const container = el('div', { className: 'tool-fields' })
      for (const field of descriptors) {
        const label = prefix + field.label, value = target[field.key] === undefined ? field.fallback : target[field.key]
        if (field.type === 'object') { container.append(toolSection(label, [controls(target[field.key], field.fields, `${label} `)])); continue }
        if (field.type === 'list') {
          const listNode = el('div')
          function draw() {
            listNode.replaceChildren()
            target[field.key].forEach((row, i) => {
              const singular = field.label.toLowerCase(), rowLabel = `${label} ${i + 1}`
              const content = []
              if (field.key === 'placements') content.push(output(`${rowLabel} Output crossover ID`, row.crossover_id))
              const item = field.fields[0].key === '$value' ? { $value: row } : row
              content.push(controls(item, field.fields, `${rowLabel} `, () => { if (field.fields[0].key === '$value') target[field.key][i] = item.$value }))
              const up = createButton({ label: 'Move up', onClick: () => { if (i > 0) { [target[field.key][i - 1], target[field.key][i]] = [target[field.key][i], target[field.key][i - 1]]; draw() } } })
              const down = createButton({ label: 'Move down', onClick: () => { if (i + 1 < target[field.key].length) { [target[field.key][i + 1], target[field.key][i]] = [target[field.key][i], target[field.key][i + 1]]; draw() } } })
              up.setAttribute('aria-label', `Move ${singular} ${i + 1} up`); up.disabled = i === 0
              down.setAttribute('aria-label', `Move ${singular} ${i + 1} down`); down.disabled = i + 1 === target[field.key].length
              const remove = createButton({ label: 'Remove', onClick: () => { target[field.key].splice(i, 1); draw() } })
              remove.setAttribute('aria-label', `Remove ${singular} ${i + 1}`)
              content.push(el('div', { className: 'tool-fields', children: [up, down, remove] }))
              listNode.append(toolSection(rowLabel, content))
            })
            listNode.append(createButton({ label: `Add ${field.label.toLowerCase()}`, onClick: () => {
              target[field.key].push(field.defaults())
              try { cloneInput(values) } catch (failure) { target[field.key].pop(); fail(failure.message); return }
              draw()
            } }))
          }
          draw(); container.append(listNode); continue
        }
        let input
        const update = next => { target[field.key] = next; changed(); refreshDomainHelp() }
        if (field.type === 'choice') {
          input = el('select', { className: 'input input--sm', attrs: { 'aria-label': label }, children: field.choices.map(choice => el('option', { attrs: { value: choice }, text: String(choice) })),
            on: { change: event => update(field.choices.find(choice => String(choice) === event.target.value)) } })
          input.value = String(value)
        } else if (field.type === 'boolean') {
          input = el('input', { attrs: { type: 'checkbox', 'aria-label': label }, on: { change: event => update(event.target.checked) } }); input.checked = value
        } else {
          const numeric = field.type === 'integer' || field.type === 'number'
          input = el('input', { className: 'input input--sm', attrs: { type: numeric ? 'number' : 'text', value: value ?? '', 'aria-label': label,
            ...(numeric ? { step: field.type === 'integer' ? '1' : 'any' } : {}), ...(field.resource ? { list: catalogs.get(field.resource) } : {}) },
          on: { input: event => update(numeric ? (event.target.value === '' ? NaN : Number(event.target.value))
            : field.type === 'nullable' && event.target.value === '' ? null : event.target.value) } })
        }
        container.append(el('label', { children: [label, input] }))
        if (field.type === 'nullable') container.append(el('p', { className: 'tool-help', text: 'Blank stores no process ID.' }))
      }
      const help = descriptors.some(field => field.key === 'domain_index') ? el('p', { className: 'tool-help' }) : null
      function refreshDomainHelp() {
        if (!help) return
        const domains = strands.get(target.strand_id)?.domains
        help.textContent = domains ? `Prefix domains: ${domains.map((domain, index) => `${index}: ${domain.helix_id} ${domain.start_bp}→${domain.end_bp}`).join('; ')}` : 'Choose a prefix strand to inspect its domain ordinals.'
      }
      refreshDomainHelp(); if (help) container.append(help)
      return container
    }
    if (empty) form.append(el('p', { text: 'This step clears all loops and skips. It has no editable inputs and follows upstream changes during replay. Use the history row’s Delete or Revert action to remove this step.' }))
    else {
      form.append(controls(values, fields))
      if (kind.includes('extra-bases')) form.append(el('p', { className: 'tool-help', text: 'Sequence uses A/C/G/T/N. An empty sequence clears the junction’s extra bases.' }))
      if (kind === 'loop-skip-clear') form.append(el('p', { className: 'tool-help', text: 'Clear range includes the start plane and excludes the end plane.' }))
    }
    body.append(form, error)
    async function save() {
      if (settled || saving) return
      if (!isCurrent()) { fail('The part changed. Reopen this routing editor.'); return }
      let params
      try { validate(values, fields); params = cloneInput(values) } catch (failure) { fail(failure.message); return }
      if (!onSave) { finish(params); modal.close(); return }
      saving = true
      const nodes = [...modal.root.querySelectorAll('input,select,button')], disabled = nodes.map(node => node.disabled)
      nodes.forEach(node => { node.disabled = true })
      try {
        const result = await onSave(params)
        if (settled) return
        if (result == null) throw new Error('The routing edit was not accepted. Your draft is unchanged.')
        saving = false; finish(params); modal.close()
      } catch (failure) {
        if (settled) return
        saving = false; nodes.forEach((node, i) => { node.disabled = disabled[i] }); fail(failure?.message || 'The routing edit failed.')
      }
    }
    const modal = createModal({ title: `Edit ${title}`, size: 'lg', body,
      actions: [createButton({ label: empty ? 'Close' : 'Cancel', onClick: () => modal.close() }), ...(!empty ? [createButton({ label: 'Apply', variant: 'primary', onClick: save })] : [])],
      onClose: () => { if (saving && !retired) return false; finish(null) },
    })
    modal.root.setAttribute('aria-label', `Edit ${title}`)
    modal.open(); window.addEventListener('nadoc:document-reset', reset)
  })
}

/** One visible load, then one local draft. Closing a load never opens a late modal. */
export async function openRoutingFeatureEditor({ api, index, subIndex, parent, child }) {
  const context = api.captureRoutingEditContext()
  let retired = false
  const message = el('p', { text: 'Loading native references before this routing step…' })
  const reset = () => loading.close()
  const loading = createModal({ title: 'Fine Routing inputs', body: message,
    actions: [createButton({ label: 'Cancel', onClick: () => loading.close() })],
    onClose: () => { retired = true; window.removeEventListener('nadoc:document-reset', reset) },
  })
  loading.open(); window.addEventListener('nadoc:document-reset', reset)
  try {
    const packet = await api.getRoutingFeatureInputs(index, subIndex, context, parent.id, child.id)
    if (retired) return null
    if (!api.isRoutingEditContextCurrent(context)) throw new Error('The part changed. Reopen this routing editor.')
    draftInputs(packet) // Keep a malformed-definition error in the visible load dialog.
    loading.close()
    return await editRoutingFeature(packet, { isCurrent: () => api.isRoutingEditContextCurrent(context),
      onSave: params => api.editRoutingFeatureInputs(index, subIndex, params, context, parent.id, child.id) })
  } catch (failure) {
    if (retired) return null
    message.setAttribute('role', 'alert'); message.textContent = failure?.message || 'Routing inputs could not be loaded.'
    return null
  }
}

/** Thin Feature Log entry; snapshot/diff eviction is not input eligibility. */
export function createRoutingEditAction({ api, design, parent, child, index, subIndex, enabled, assemblyActive }) {
  if (!enabled || assemblyActive || !isNativeRoutingChild(parent, child)) return null
  const latest = (design.feature_log_cursor ?? -1) === -1 && design.feature_log_sub_cursor == null
  const edit = createButton({ label: '✎', size: 'sm', onClick: async event => {
    event.stopPropagation(); edit.disabled = true
    try { await openRoutingFeatureEditor({ api, index, subIndex, parent, child }) }
    finally { if (edit.isConnected) edit.disabled = !latest }
  } })
  edit.disabled = !latest
  edit.title = latest ? `Edit ${child.label} inputs` : 'Return to the latest history position before editing routing inputs.'
  return edit
}
