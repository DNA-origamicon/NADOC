import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { toolSection } from './tool_sections.js'

const TITLES = Object.freeze({
  'bundle-create': 'Bundle', 'extrude-segment': 'Extrude Segment',
  'extrude-continuation': 'Continuation', 'extrude-deformed-continuation': 'Deformed Continuation',
  'circle-segment': 'Circle Segment', 'extrude-frame': 'Frame Extrusion', 'overhang-extrude': 'Overhang Extrusion',
})
const OWN = (object, key) => Object.prototype.hasOwnProperty.call(object, key)

/** UI eligibility only; the server proves the complete recipe before editing. */
export function isNativeExtrusionFeature(entry) {
  const params = entry?.params
  return entry?.feature_type === 'snapshot' && OWN(TITLES, entry.op_kind)
    && params?._proof_version === 1 && typeof params.history_seed === 'string' && params.history_seed.length > 0
    && !OWN(params, '_generator') && !OWN(params, '_generated_scope')
}

/** Saved native inputs, never a lookup or geometry edit on the displayed design. */
export function editExtrusionFeature(entry, { onSave, isCurrent = () => true } = {}) {
  if (!isNativeExtrusionFeature(entry)) return Promise.reject(new Error('This extrusion has no supported native input contract.'))
  return new Promise(resolve => {
    const kind = entry.op_kind, values = structuredClone(entry.params)
    const circle = kind === 'circle-segment', overhang = kind === 'overhang-extrude'
    const frame = kind === 'extrude-frame', deformed = kind === 'extrude-deformed-continuation'
    let frameMode = values.source_legacy_plane ? 'legacy' : values.source_frame_id ? 'source' : 'independent'
    let deformedMode = values.source_bp == null ? 'saved' : 'derived'
    let saving = false, settled = false, retired = false
    const body = el('div'), error = el('p', { className: 'tool-help', attrs: { role: 'alert' } })
    error.hidden = true
    const fail = message => { error.textContent = message; error.hidden = false }
    const finish = value => {
      if (settled) return
      settled = true; window.removeEventListener('nadoc:document-reset', reset); resolve(value)
    }
    const reset = () => { retired = true; modal.close() }
    const valueOf = (key, fallback) => values[key] ?? fallback
    function number(label, value, change, integer = false) {
      const input = el('input', { className: 'input input--sm', attrs: { type: 'number', step: integer ? '1' : 'any', value, 'aria-label': label },
        on: { input: event => change(event.target.value === '' ? NaN : Number(event.target.value)) } })
      return el('label', { children: [label, input] })
    }
    function scalar(key, label, fallback = 0, integer = false) {
      return number(label, valueOf(key, fallback), value => { values[key] = value }, integer)
    }
    function text(key, label, fallback = '', optional = false, maxLength = 512) {
      return el('label', { children: [label, el('input', { className: 'input input--sm', attrs: { type: 'text', value: valueOf(key, fallback), maxlength: maxLength, 'aria-label': label },
        on: { input: event => { values[key] = optional && event.target.value === '' ? null : event.target.value } } })] })
    }
    function select(label, value, options, change) {
      const input = el('select', { className: 'input input--sm', attrs: { 'aria-label': label },
        children: options.map(option => { const [key, name] = Array.isArray(option) ? option : [option, option]; return el('option', { attrs: { value: key }, text: name }) }),
        on: { change: event => change(event.target.value) } })
      input.value = value
      return el('label', { children: [label, input] })
    }
    const choice = (key, label, fallback, options) => select(label, valueOf(key, fallback), options, value => { values[key] = value })
    function check(key, label, fallback = true) {
      const input = el('input', { attrs: { type: 'checkbox', 'aria-label': label }, on: { change: event => { values[key] = event.target.checked } } })
      input.checked = valueOf(key, fallback)
      return el('label', { children: [input, label] })
    }
    function vector(key, title, fallback, axes = ['X', 'Y', 'Z'], unit = '') {
      const row = el('div', { className: 'tool-fields' })
      for (const [i, axis] of axes.entries()) row.append(number(`${title} ${axis}${unit}`, valueOf(key, fallback)[i], value => {
        if (!Array.isArray(values[key])) values[key] = [...fallback]
        values[key][i] = value
      }))
      return toolSection(title, [row])
    }
    const dimensions = el('div', { className: 'tool-fields' })
    if (!circle) dimensions.append(scalar('length_bp', 'Length (bp)', NaN, true))
    if (kind === 'bundle-create' || frame) dimensions.append(text('name', 'Name', frame ? 'Extrude' : 'Bundle', false, 128))
    if (!overhang) dimensions.append(choice('plane', 'Plane', 'XY', ['XY', 'XZ', 'YZ']))
    if (['extrude-segment', 'extrude-continuation', 'circle-segment'].includes(kind)) dimensions.append(scalar('offset_nm', 'Offset (nm)'))
    body.append(toolSection('Extrusion', [dimensions, el('p', { className: 'tool-help', text: circle || overhang
      ? 'Lengths are positive base-pair counts.' : 'A negative length extrudes in the opposite direction.' })]))

    if (!overhang) {
      const cells = el('div'), invalidCells = !Array.isArray(values.cells) || values.cells.length > 512
      function drawCells() {
        cells.replaceChildren()
        if (invalidCells) { cells.append(el('p', { text: 'This editor requires at most 512 saved cells.' })); return }
        const table = el('table', { attrs: { 'aria-label': 'Lattice cells' } })
        table.append(el('thead', { children: [el('tr', { children: ['Row', 'Column', ...(circle ? ['Length (bp)'] : []), ''].map(label => el('th', { text: label })) })] }))
        const rows = el('tbody')
        values.cells.forEach((cell, i) => {
          const fields = [0, 1].map((j) => el('td', { children: [number(`Cell ${i + 1} ${j ? 'column' : 'row'}`, cell[j], value => { values.cells[i][j] = value }, true)] }))
          if (circle) fields.push(el('td', { children: [number(`Cell ${i + 1} length (bp)`, values.cell_lengths?.[i] ?? NaN, value => { values.cell_lengths[i] = value }, true)] }))
          fields.push(el('td', { children: [el('button', { attrs: { type: 'button', 'aria-label': `Remove cell ${i + 1}` }, text: 'Remove', on: { click: () => {
            values.cells.splice(i, 1); if (circle) values.cell_lengths.splice(i, 1); drawCells()
          } } })] }))
          rows.append(el('tr', { children: fields }))
        })
        table.append(rows); cells.append(table)
        const add = createButton({ label: 'Add cell', onClick: () => {
          if (values.cells.length >= 512) return
          values.cells.push([0, 0]); if (circle) values.cell_lengths.push(1); drawCells()
        } })
        add.disabled = values.cells.length >= 512; cells.append(add)
      }
      if (circle && !Array.isArray(values.cell_lengths)) values.cell_lengths = []
      drawCells(); body.append(toolSection('Cells', [cells]))
    }
    if (kind === 'bundle-create') body.append(toolSection('Lattice', [choice('lattice_type', 'Lattice', 'HONEYCOMB', ['HONEYCOMB', 'SQUARE'])]))
    if (['bundle-create', 'extrude-segment', 'extrude-continuation', 'circle-segment'].includes(kind))
      body.append(toolSection('Strands', [choice('strand_filter', 'Strands', 'both', [['both', 'Scaffold and staples'], ['scaffold', 'Scaffold'], ['staples', 'Staples']]), check('ligate_adjacent', 'Ligate adjacent ends')]))
    if (!overhang) body.append(toolSection('Placement organization', [check('separate_fresh_extrusions', 'Separate fresh extrusions')]))
    if (kind === 'extrude-continuation') body.append(toolSection('Continuation source', [text('source_frame_id', 'Source frame ID', '', true, 128),
      check('extend_inplace', 'Extend existing helix in place'), el('p', { className: 'tool-help', text: 'Blank uses the saved plane. Source identities are resolved in the rebuilt history prefix.' })]))
    let refreshMode = () => {}
    if (deformed) {
      const bp = scalar('source_bp', 'Source bp', 0, true)
      const vectors = [vector('grid_origin', 'Grid origin', [0, 0, 0], undefined, ' (nm)'), vector('axis_dir', 'Axis direction', [0, 0, 1]),
        vector('frame_right', 'Frame right', [1, 0, 0]), vector('frame_up', 'Frame up', [0, 1, 0])]
      refreshMode = () => {
        bp.querySelector('input').disabled = deformedMode !== 'derived'
        vectors.forEach(section => section.querySelectorAll('input').forEach(input => { input.disabled = deformedMode === 'derived' }))
      }
      body.append(toolSection('Deformed frame', [select('Frame definition', deformedMode, [['derived', 'Recompute from source bp'], ['saved', 'Saved frame vectors']], value => { deformedMode = value; refreshMode() }),
        text('ref_helix_id', 'Reference helix ID', '', true), bp, el('p', { className: 'tool-help', text: 'Recomputed mode uses native geometry at the saved source bp; the stored frame vectors are retained and ignored.' })]), ...vectors)
      refreshMode()
    }
    if (frame) {
      const source = text('source_frame_id', 'Source frame ID', '', true, 128)
      const vectors = [vector('translation_nm', 'Translation', [0, 0, 0], undefined, ' (nm)'), vector('rotation_xyzw', 'Rotation', [0, 0, 0, 1], ['X', 'Y', 'Z', 'W'])]
      refreshMode = () => {
        source.querySelector('input').disabled = frameMode !== 'source'
        vectors.forEach(section => section.querySelectorAll('input').forEach(input => { input.disabled = frameMode !== 'independent' }))
      }
      body.append(toolSection('Frame source', [select('Frame source', frameMode, [['independent', 'Independent placement'], ['source', 'Existing frame'], ['legacy', 'Legacy plane']], value => { frameMode = value; refreshMode() }), source,
        el('p', { className: 'tool-help', text: 'An existing frame or legacy plane supplies the placement. Independent placement uses translation and an XYZW quaternion.' })]), ...vectors)
      refreshMode()
    }
    if (overhang) body.append(toolSection('Source endpoint and neighbor', [text('helix_id', 'Source helix ID'), scalar('bp_index', 'Endpoint bp', NaN, true),
      choice('direction', 'Direction', 'FORWARD', ['FORWARD', 'REVERSE']), select('Strand end', values.is_five_prime ? '5' : '3', [['5', '5′'], ['3', '3′']], value => { values.is_five_prime = value === '5' }),
      scalar('neighbor_row', 'Neighbor row', NaN, true), scalar('neighbor_col', 'Neighbor column', NaN, true), check('reuse_existing_helix', 'Reuse existing helix')]))
    body.append(error)

    function submission() {
      const result = structuredClone(values)
      if (deformed) result.source_bp = deformedMode === 'saved' ? null : valueOf('source_bp', 0)
      if (frame) {
        result.source_legacy_plane = frameMode === 'legacy'
        result.source_frame_id = frameMode === 'source' ? values.source_frame_id : null
        if (frameMode !== 'independent') { result.translation_nm = [0, 0, 0]; result.rotation_xyzw = [0, 0, 0, 1] }
      }
      const integer = value => Number.isSafeInteger(value)
      const length = value => integer(value) && (circle || overhang ? value > 0 : value !== 0)
      if (!circle && !length(result.length_bp)) throw new Error('Use a nonzero integer length; overhang lengths must be positive.')
      if (!overhang) {
        if (!Array.isArray(result.cells) || !result.cells.length || result.cells.length > 512
            || result.cells.some(cell => !Array.isArray(cell) || cell.length !== 2 || !cell.every(integer)))
          throw new Error('Use 1–512 cells with integer row and column values.')
        if (new Set(result.cells.map(cell => `${cell[0]},${cell[1]}`)).size !== result.cells.length) throw new Error('Each lattice cell must be unique.')
        if (circle && (result.cell_lengths?.length !== result.cells.length || !result.cell_lengths.every(length))) throw new Error('Every circle cell needs a positive integer length.')
      }
      if (overhang && (!result.helix_id || ![result.bp_index, result.neighbor_row, result.neighbor_col].every(integer))) throw new Error('Specify the source helix and integer endpoint and neighbor coordinates.')
      // Match the existing native input work allowance, without evaluating DNA.
      const work = circle ? result.cell_lengths.reduce((sum, count) => sum + count, 0)
        : Math.abs(result.length_bp) * (overhang ? 1 : result.cells.length)
      if (work > 50_000) throw new Error('This history edit exceeds the 50,000 base-pair-cell limit. Reduce the cells or lengths.')
      if (result.offset_nm != null && !Number.isFinite(result.offset_nm)) throw new Error('Use a finite offset.')
      const validVector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite)
      if (deformed) {
        if (deformedMode === 'derived' && !integer(result.source_bp)) throw new Error('Use an integer source bp.')
        for (const key of ['grid_origin', 'axis_dir', 'frame_right', 'frame_up']) if (!validVector(result[key], 3)) throw new Error('Frame vectors require three finite coordinates.')
        if (deformedMode === 'saved' && ['axis_dir', 'frame_right', 'frame_up'].some(key => result[key].every(value => value === 0))) throw new Error('Frame directions must be nonzero.')
      }
      if (frame && ((!validVector(result.translation_nm ?? [0, 0, 0], 3)) || !validVector(result.rotation_xyzw ?? [0, 0, 0, 1], 4)
          || (result.rotation_xyzw ?? [0, 0, 0, 1]).every(value => value === 0))) throw new Error('Use finite translation coordinates and a nonzero quaternion.')
      if (frameMode === 'source' && frame && !result.source_frame_id) throw new Error('Specify the source frame ID.')
      if ((kind === 'bundle-create' || frame) && !(result.name ?? (frame ? 'Extrude' : 'Bundle')).trim()) throw new Error('Enter a name.')
      return result
    }
    async function save() {
      if (saving || settled) return
      if (!isCurrent()) { fail('The part changed. Reopen this extrusion editor.'); return }
      let params
      try { params = submission() } catch (failure) { fail(failure.message); return }
      if (!onSave) { finish(params); modal.close(); return }
      saving = true
      const controls = [...modal.root.querySelectorAll('input, select, button')], disabled = controls.map(control => control.disabled)
      controls.forEach(control => { control.disabled = true })
      try {
        const result = await onSave(params)
        if (settled) return
        if (result == null) throw new Error('The extrusion edit was not accepted. Your draft is unchanged.')
        saving = false; finish(params); modal.close()
      } catch (failure) {
        if (settled) return
        saving = false; controls.forEach((control, i) => { control.disabled = disabled[i] })
        fail(failure?.message || 'The extrusion edit failed.')
      }
    }
    const modal = createModal({ title: `Edit ${TITLES[kind]}`, size: 'lg', body,
      actions: [createButton({ label: 'Cancel', onClick: () => modal.close() }), createButton({ label: 'Save', variant: 'primary', onClick: save })],
      onClose: () => { if (saving && !retired) return false; finish(null) },
    })
    modal.root.setAttribute('aria-label', `Edit ${TITLES[kind]}`)
    modal.open(); window.addEventListener('nadoc:document-reset', reset)
  })
}
