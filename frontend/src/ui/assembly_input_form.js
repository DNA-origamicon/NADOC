/** Typed assembly command controls. No JSON editing or inferred construction inputs. */
const words = key => (key === '_targets' ? 'Operation targets' : key).replaceAll('_', ' ').replace(/\bid\b/g, '').replace(/\bids\b/g, '').trim().replace(/^./, s => s.toUpperCase())
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const clone = value => value === undefined ? undefined : structuredClone(value)

export function referenceKind(key) {
  if (/instance.*id|instance_ids/.test(key)) return 'instance'
  if (/joint.*id/.test(key)) return 'joint'
  if (/group.*id/.test(key)) return 'group'
  if (key === 'belt_path_id' || key === 'belt_id') return 'belt'
  for (const name of ['binding', 'connection', 'duplex', 'relation']) if (key === `${name}_id`) return name
  if (key === 'rider_id') return 'rider'
  if (/sub_domain.*id/.test(key)) return 'sub_domain'
  if (/overhang.*id/.test(key)) return 'overhang'
  if (/cluster.*id/.test(key)) return 'cluster'
  if (/connector.*label/.test(key)) return 'connector'
  return null
}

export function inputDefault(schema) {
  if (schema.default != null) return clone(schema.default)
  if (schema.enum) return schema.enum[0]
  if (schema.format === 'matrix') return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
  if (schema.type === 'object') return Object.fromEntries((schema.required ?? []).map(key => [key, inputDefault(schema.properties[key])]))
  if (schema.type === 'array') return Array.from({ length: schema.minItems ?? 0 }, () => inputDefault(schema.items))
  if (schema.type === 'boolean') return false
  if (['number', 'integer'].includes(schema.type)) return schema.minimum ?? 0
  return ''
}

/** Validate the actual typed tree and return a field-specific error, if any. */
export function validateInput(schema, value, label = 'Input') {
  if (value === null && schema.nullable) return null
  if (schema.enum && !schema.enum.includes(value)) return `${label}: select a supported value.`
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return `${label}: enter the required fields.`
    for (const key of schema.required ?? []) if (value[key] === undefined) return `${label}: ${words(key)} is required.`
    for (const [key, item] of Object.entries(value)) {
      if (!schema.properties[key]) return `${label}: unknown field ${key}.`
      const error = validateInput(schema.properties[key], item, `${label} / ${words(key)}`)
      if (error) return error
    }
  } else if (schema.type === 'array') {
    if (!Array.isArray(value) || value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? 4096)) return `${label}: invalid number of entries.`
    for (let i = 0; i < value.length; i++) {
      const error = validateInput(schema.items, value[i], `${label} ${i + 1}`)
      if (error) return error
    }
    if (schema.format === 'vector' && /direction|normal/i.test(label) && Math.hypot(...value) < 1e-8) return `${label}: direction must be nonzero.`
    if (schema.format === 'matrix') {
      if (value.slice(12).some((n, i) => Math.abs(n - (i === 3 ? 1 : 0)) > 1e-6)) return `${label}: last row must be 0, 0, 0, 1.`
      const rows = [value.slice(0, 3), value.slice(4, 7), value.slice(8, 11)]
      if (rows.some((a, i) => rows.some((b, j) => Math.abs(a.reduce((v, x, k) => v + x * b[k], 0) - (i === j ? 1 : 0)) > 1e-5))) return `${label}: use a rigid rotation without scaling or shear.`
      const [a,b,c] = rows
      const determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
      if (determinant < 0) return `${label}: reflections are not rigid rotations.`
    }
  } else if (['number', 'integer'].includes(schema.type)) {
    if (!Number.isFinite(value) || (schema.type === 'integer' && !Number.isSafeInteger(value))) return `${label}: enter a finite ${schema.type}.`
    if ((schema.minimum != null && value < schema.minimum) || (schema.maximum != null && value > schema.maximum)
        || (schema.exclusiveMinimum != null && value <= schema.exclusiveMinimum) || (schema.exclusiveMaximum != null && value >= schema.exclusiveMaximum)) return `${label}: value is outside the allowed range.`
  } else if (schema.type === 'boolean' ? typeof value !== 'boolean' : typeof value !== 'string') return `${label}: invalid value.`
  return null
}

export function createAssemblyInputForm({ schema, inputs, references = {} }) {
  const element = document.createElement('div')
  element.style.cssText = 'display:flex;flex-direction:column;gap:12px;max-height:65vh;overflow:auto'
  const readers = new Map()
  let serial = 0
  const options = (select, values) => {
    for (const { value, label } of values) {
      const option = document.createElement('option'); option.value = value; option.textContent = label; select.append(option)
    }
  }
  function field(node, initial, key, label, parentValue = {}, nullable = true) {
    const root = document.createElement('fieldset'), legend = document.createElement('legend')
    legend.textContent = label; root.append(legend); root.style.minWidth = '0'
    const original = initial
    if (initial === undefined) initial = node.nullable ? null : inputDefault(node)
    if (nullable && node.nullable) {
      const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = initial != null
      enabled.setAttribute('aria-label', `Set ${label}`)
      const caption = document.createElement('label'); caption.append(enabled, ' Set value'); root.append(caption)
      const child = field({ ...node, nullable: false }, initial ?? inputDefault(node), key, label, parentValue, false)
      child.element.disabled = !enabled.checked
      enabled.onchange = () => { child.element.disabled = !enabled.checked }
      root.append(child.element)
      return { element: root, read: () => enabled.checked ? child.read() : null }
    }
    if (node.type === 'object') {
      const children = new Map()
      const value = clone(initial ?? inputDefault(node))
      for (const [name, shape] of Object.entries(node.properties)) {
        const child = field(shape, value[name], name, `${label} / ${words(name)}`, value)
        root.append(child.element); children.set(name, child)
      }
      return { element: root, read: () => {
        const next = { ...value }
        for (const [name, child] of children) {
          const current = child.read()
          if (value[name] !== undefined || (node.required ?? []).includes(name) || !same(current, inputDefault(node.properties[name])) && current !== null) next[name] = current
        }
        return next
      } }
    }
    if (node.type === 'array') {
      const rows = document.createElement('div'), values = [...(initial ?? inputDefault(node))]
      let children = []
      const fixed = node.minItems === node.maxItems && node.minItems != null
      const render = () => {
        rows.replaceChildren(); children = []
        values.forEach((value, index) => {
          const child = field(node.items, value, key, `${label} ${node.format === 'vector' ? ['X', 'Y', 'Z'][index] : node.format === 'matrix' ? `row ${Math.floor(index / 4) + 1} column ${index % 4 + 1}` : index + 1}`, parentValue)
          children.push(child); rows.append(child.element)
          if (!fixed) {
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${label} ${index + 1}`)
            remove.onclick = () => { values.splice(0, values.length, ...children.map(c => c.read())); values.splice(index, 1); render() }; child.element.append(remove)
          }
        })
        if (fixed) rows.style.cssText = `display:grid;grid-template-columns:repeat(${node.format === 'matrix' ? 4 : 3},minmax(0,1fr));gap:4px`
      }
      root.append(rows); render()
      if (!fixed) {
        const add = document.createElement('button'); add.type = 'button'; add.textContent = `Add ${label}`
        add.onclick = () => { values.splice(0, values.length, ...children.map(c => c.read())); values.push(inputDefault(node.items)); render() }
        root.append(add)
      }
      return { element: root, read: () => children.map(c => c.read()) }
    }
    const reference = node.reference ?? referenceKind(key)
    let input
    if (node.enum || reference || node.type === 'boolean') {
      input = document.createElement('select')
      let choices = node.enum?.map(value => ({ value, label: value }))
        ?? (node.type === 'boolean' ? [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }] : references[reference] ?? [])
      if (reference) {
        choices = [{ value: '', label: 'Choose…' }, ...choices]
      }
      if (initial != null && !choices.some(c => String(c.value) === String(initial))) choices = [...choices, { value: initial, label: 'Recorded reference (unavailable at this history position)' }]
      options(input, choices)
      input.value = initial == null ? '' : String(initial)
    } else {
      input = document.createElement('input'); input.type = ['number', 'integer'].includes(node.type) ? 'number' : 'text'
      if (input.type === 'number') { input.step = node.type === 'integer' ? '1' : 'any'; if (node.minimum != null) input.min = node.minimum; if (node.maximum != null) input.max = node.maximum }
      input.value = initial ?? ''
    }
    input.style.cssText = 'width:100%;min-width:0'; input.id = `assembly-input-${++serial}`; input.setAttribute('aria-label', label)
    root.append(input)
    return { element: root, read: () => {
      if (node.type === 'boolean') return input.value === 'true'
      if (['number', 'integer'].includes(node.type)) return input.value.trim() === '' ? NaN : Number(input.value)
      return input.value
    }, original }
  }
  for (const [key, node] of Object.entries(schema.properties)) {
    const container = document.createElement('section'), label = words(key)
    const mode = document.createElement('select'); mode.setAttribute('aria-label', `${label} action`)
    options(mode, [{ value: 'keep', label: 'Keep recorded input' }, { value: 'set', label: 'Set input' }, ...(node.nullable ? [{ value: 'null', label: 'No value' }] : [])])
    const child = field({ ...node, nullable: false }, inputs[key] ?? inputDefault(node), key, label, inputs)
    mode.onchange = () => { child.element.disabled = mode.value === 'null' }
    const changed = () => { if (mode.value === 'keep') mode.value = 'set' }
    child.element.addEventListener('input', changed); child.element.addEventListener('change', changed); child.element.addEventListener('click', e => { if (e.target.tagName === 'BUTTON') changed() })
    container.append(mode, child.element); element.append(container)
    readers.set(key, () => mode.value === 'keep' ? { changed: false } : { changed: true, value: mode.value === 'null' ? null : child.read() })
  }
  return { element, read() {
    const patch = {}
    for (const [key, reader] of readers) {
      const { changed, value } = reader()
      if (!changed) continue
      const error = validateInput(schema.properties[key], value, words(key))
      if (error) throw new Error(error)
      patch[key] = value
    }
    if (!Object.keys(patch).length) throw new Error('Change an input before applying the edit.')
    return patch
  } }
}
