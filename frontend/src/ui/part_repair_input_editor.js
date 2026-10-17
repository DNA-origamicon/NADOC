import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

const pathKey = path => JSON.stringify(path)
const display = value => typeof value === 'string' ? value : JSON.stringify(value)

/** Small typed form renderer; catalog admission and execution belong to the backend. */
export function createRepairInputEditor({ onChange, onUpgrade, onSelect, onSource, onError, getSelectedFile = () => null }) {
  const root = el('div', { className: 'part-repair__inputs' }), choices = new Map()
  let catalog = null, disabled = false
  function fileButton(label, field, operation, source = field.source_binding.source) {
    const picker = el('input', { attrs: { type: 'file', hidden: true } })
    const button = createButton({ label, size: 'sm', onClick: () => {
      const selected = operation === 'stage_proposed' ? getSelectedFile(source) : null
      if (selected) Promise.resolve(onSource(field, selected, operation, source)).catch(onError)
      else picker.click()
    } })
    picker.addEventListener('change', () => {
      const file = picker.files?.[0]
      picker.value = ''
      if (file) Promise.resolve(onSource(field, file, operation, source)).catch(onError)
    })
    return el('span', { children: [button, picker] })
  }
  function render(next, actions = []) {
    catalog = next; root.replaceChildren(); choices.clear()
    if (!catalog) { root.append(el('p', { text: 'Select a feature and inspect its editable inputs.' })); return }
    if (!catalog.definition_supported) {
      root.append(el('p', { text: catalog.reason?.detail ?? 'This definition needs a reviewed repair input editor.' })); return
    }
    root.append(el('p', { className: 'part-repair__muted', text: 'Inputs only. Reference validity and the complete result are checked by Evaluate.' }))
    for (const upgrade of catalog.upgrades ?? []) {
      const connection = upgrade?.action?.action === 'upgrade_connection_owners'
      if ((!connection && upgrade?.action?.action !== 'upgrade_cluster_creation') || typeof upgrade.label !== 'string') continue
      root.append(el('div', { className: 'part-repair__field', children: [
        el('strong', { text: connection ? 'Connection reference repair' : 'Structural repair' }),
        el('small', { text: connection ? 'Follow the original native connection creator across length changes. Save and evaluate the proposal before applying it.' : 'Keep group owners referenced by later features. Save and evaluate the proposal before applying it.' }),
        createButton({ label: upgrade.label, size: 'sm', onClick: () => {
          try { onUpgrade(upgrade) } catch (error) { onError(error) }
        } }),
      ] }))
    }
    for (const field of catalog.fields) {
      const row = el('div', { className: 'part-repair__field', dataset: { repairPath: pathKey(field.parameter_path) }, attrs: { tabindex: -1 } })
      const saved = actions.find(action => action.action === 'set_input' && action.feature_id === catalog.feature_id
        && (action.child_id ?? null) === (catalog.child_id ?? null) && pathKey(action.parameter_path) === pathKey(field.parameter_path))
      const proposed = saved ? saved.value : field.expected_old
      row.append(el('strong', { text: field.label }), el('small', { text: `Published: ${display(field.expected_old)}`, className: 'part-repair__old' }))
      if (field.input_type === 'reference') {
        const candidates = el('div', { className: 'part-repair__choices' })
        choices.set(pathKey(field.parameter_path), { field, candidates })
        row.append(createButton({ label: 'Find replacements', size: 'sm', onClick: () => {
          try { Promise.resolve(onSelect(field)).catch(onError) } catch (error) { onError(error) }
        } }), candidates)
      } else if (field.input_type === 'source') {
        row.append(el('small', { text: `Maximum ${field.source_binding.max_size_bytes.toLocaleString()} bytes; original file contents only.` }))
        row.append(fileButton('Restore original file', field, 'restore_published'))
        if (field.source_binding.replacement_supported) row.append(fileButton('Propose replacement file', field, 'replace'))
        if (saved) {
          row.append(el('small', { text: `Saved replacement: ${saved.value.sha256 ?? 'invalid descriptor'}` }),
            fileButton('Upload saved replacement file', field, 'stage_proposed', saved.value))
        }
      } else {
        const inputs = [], nullable = field.nullable ? el('input', { attrs: { type: 'checkbox', 'aria-label': `${field.label}: no value` } }) : null
        if (nullable) { nullable.checked = proposed === null; row.append(el('label', { children: [nullable, ' No value'] })) }
        const addInput = (type, value, label) => {
          const input = el('input', { attrs: { type, 'aria-label': label,
            min: field.minimum ?? field.exclusive_minimum, max: field.maximum, maxLength: field.max_length,
            step: field.input_type === 'integer' ? 1 : 'any' } })
          if (type === 'checkbox') input.checked = !!value
          else input.value = value == null ? '' : String(value)
          input.addEventListener('input', () => { if (nullable) nullable.checked = false })
          inputs.push(input); return input
        }
        if (field.input_type === 'number_list') {
          const grid = el('div', { className: 'part-repair__matrix' })
          if (!Number.isSafeInteger(field.length) || field.length < 1 || field.length > 64) {
            row.append(el('p', { text: 'This field exceeds the reviewed editor size.' })); root.append(row); continue
          }
          for (let index = 0; index < field.length; index++) grid.append(addInput('number', proposed?.[index], `${field.label} ${index + 1}`))
          row.append(grid)
        } else if (['number', 'integer', 'string', 'boolean'].includes(field.input_type)) {
          row.append(addInput(field.input_type === 'boolean' ? 'checkbox' : field.input_type === 'string' ? 'text' : 'number', proposed, field.label))
        } else { row.append(el('p', { text: 'This field requires a reviewed editor.' })); root.append(row); continue }
        row.append(createButton({ label: 'Add proposed change', size: 'sm', onClick: () => {
          try {
            const value = nullable?.checked ? null : field.input_type === 'number_list' ? inputs.map(input => input.value)
              : field.input_type === 'boolean' ? inputs[0].checked : inputs[0].value
            onChange(field, value)
          } catch (error) { onError(error) }
        } }))
      }
      root.append(row)
    }
    setDisabled(disabled)
  }
  function setDisabled(value) {
    disabled = value
    for (const input of root.querySelectorAll('input,button,select')) input.disabled = disabled
  }
  function setSelection(selection) {
    for (const { candidates } of choices.values()) candidates.replaceChildren()
    if (!selection || selection.target?.feature_id !== catalog?.feature_id
        || (selection.target.child_id ?? null) !== (catalog.child_id ?? null)) return
    const entry = choices.get(pathKey(selection.target.parameter_path))
    if (!entry) return
    entry.candidates.append(el('small', { text: 'Choices exist before this feature; the full repair still needs evaluation.' }))
    for (const candidate of selection.candidates ?? []) entry.candidates.append(createButton({
      label: `${candidate.label ?? candidate.identity} (${candidate.identity})`, size: 'sm',
      onClick: () => { try { onChange(entry.field, candidate.identity) } catch (error) { onError(error) } },
    }))
    if (!selection.candidates?.length) entry.candidates.append(el('small', { text: 'No eligible replacement was found.' }))
    if (selection.truncated) entry.candidates.append(el('small', { text: 'The candidate list is limited. Refine the source feature before retrying.' }))
    setDisabled(disabled)
  }
  return { root, render, setDisabled, setSelection,
    focusPath(path) {
      const row = [...root.querySelectorAll('[data-repair-path]')].find(item => item.dataset.repairPath === pathKey(path))
      row?.focus(); row?.scrollIntoView?.({ block: 'nearest' })
    } }
}
