/** Shared ordinary terminal editor; API receipts, not transport completion, close it. */
const MODIFICATIONS = { cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA', bhq1: 'BHQ-1',
  bhq2: 'BHQ-2', atto488: 'ATTO 488', atto550: 'ATTO 550', biotin: 'Biotin' }
let active = null

export function openStrandExtensionDialog({ x, y, strandIds, existingByStrand, api,
  getError = () => null, id = '__ext-dialog', allowRemove = false, context = api.captureExtensionContext() }) {
  active?.close()
  const ids = [...strandIds]
  const pair = ids.length === 1 ? existingByStrand.get(ids[0]) ?? {} : {}
  const hasAny = [...existingByStrand.values()].some(value => value.five_prime || value.three_prime)
  const removeIds = [...new Set([...existingByStrand.values()].flatMap(value =>
    [value.five_prime?.id, value.three_prime?.id].filter(Boolean)))]
  let end = pair.five_prime && pair.three_prime ? 'both' : pair.three_prime ? 'three_prime' : 'five_prime'
  const prefill = end === 'both' ? null : pair[end]
  let closed = false, busy = false
  const node = document.createElement('div'); node.id = id
  node.style.cssText = `position:fixed;left:${Math.max(0, Math.min(x + 8, window.innerWidth - 290))}px;top:${Math.max(0, Math.min(y + 8, window.innerHeight - 390))}px;width:280px;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px 16px;z-index:10000;box-shadow:0 8px 24px rgba(0,0,0,.6);font-size:13px;color:#c9d1d9;user-select:none;`
  const add = (tag, text, parent = node) => {
    const item = document.createElement(tag); if (text) item.textContent = text
    parent.appendChild(item); return item
  }
  const title = add('div', hasAny ? 'Edit extensions' : ids.length > 1 ? `Add extension to ${ids.length} strands` : 'Add extension')
  title.style.cssText = 'font-weight:700;margin-bottom:10px;color:#cde'
  const endRow = add('div'); endRow.style.cssText = 'display:flex;gap:12px;margin-bottom:10px'
  for (const [value, text] of [['five_prime', '5′'], ['three_prime', '3′'], ['both', 'Both']]) {
    const label = add('label', null, endRow), radio = add('input', null, label)
    radio.type = 'radio'; radio.name = `${id}-end`; radio.value = value; radio.checked = value === end
    radio.addEventListener('change', () => { end = value }); label.appendChild(document.createTextNode(text))
  }
  const field = (name, text, value, tag = 'input') => {
    const label = add('label', text); label.style.cssText = 'display:block;font-size:11px;color:#8899aa;margin:8px 0 4px'
    const input = add(tag, null, label); input.name = name; input.value = value ?? ''
    input.style.cssText = 'display:block;width:100%;box-sizing:border-box;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:5px 8px;outline:none'
    return input
  }
  const sequence = field('sequence', 'Sequence (ACGTN, optional):', prefill?.sequence)
  sequence.placeholder = 'e.g. TTTT'
  const seqHint = add('div'); seqHint.style.cssText = 'font-size:11px;color:#8899aa;min-height:14px'
  sequence.addEventListener('input', () => {
    const value = sequence.value.trim().toUpperCase(), valid = !value || /^[ACGTN]+$/.test(value)
    seqHint.textContent = valid ? value ? `${value.length} bp` : '' : 'Only A, C, G, T, N allowed'
    seqHint.style.color = valid ? '#8899aa' : '#ff6b6b'
  })
  const modification = field('modification', 'Modification:', null, 'select')
  for (const [value, text] of [['', 'None'], ...Object.entries(MODIFICATIONS)]) {
    const option = add('option', text, modification); option.value = value
  }
  modification.value = prefill?.modification ?? ''
  const label = field('label', 'Label (optional):', prefill?.label); label.placeholder = 'e.g. Cy3 dye'
  const error = add('div'); error.style.cssText = 'font-size:11px;color:#ff6b6b;min-height:14px;margin:8px 0 6px'
  const buttons = add('div'); buttons.style.cssText = 'display:flex;gap:8px;justify-content:flex-end'
  const button = (text, parent = buttons) => {
    const value = add('button', text, parent)
    value.style.cssText = 'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:5px 14px;cursor:pointer;font-size:12px'
    return value
  }
  const cancel = button('Cancel'), apply = button('Apply')
  apply.style.background = '#238636'
  const remove = allowRemove && hasAny ? button('Remove all extensions', node) : null
  const controls = [...node.querySelectorAll('input,select,button')].filter(control => control !== cancel)
  async function submit(work) {
    if (closed || busy) return
    busy = true; error.textContent = ''; controls.forEach(control => { control.disabled = true })
    apply.textContent = '…'
    try {
      const receipt = await work()
      if (closed) return
      if (!receipt) {
        const detail = getError()?.message
        throw new Error(typeof detail === 'string' ? detail : detail?.message || 'The extension edit was not confirmed. Refresh before retrying.')
      }
      close()
    } catch (failure) {
      if (!closed) error.textContent = failure?.message || 'Error saving extension.'
    } finally {
      if (!closed) { busy = false; controls.forEach(control => { control.disabled = false }); apply.textContent = 'Apply' }
    }
  }
  apply.addEventListener('click', () => {
    if (closed || busy) return
    const seq = sequence.value.trim().toUpperCase() || null, mod = modification.value || null
    if (!seq && !mod) { error.textContent = 'Provide at least a sequence or modification.'; return }
    if (seq && !/^[ACGTN]+$/.test(seq)) { error.textContent = 'Sequence contains invalid characters.'; return }
    const ends = end === 'both' ? ['five_prime', 'three_prime'] : [end]
    const items = ids.flatMap(strandId => ends.map(value => ({ strandId, end: value,
      sequence: seq, modification: mod, label: label.value.trim() || null })))
    void submit(() => api.upsertStrandExtensionsBatch(items, context))
  })
  remove?.addEventListener('click', () => { void submit(() => api.deleteStrandExtensionsBatch(removeIds, context)) })
  cancel.addEventListener('click', close)
  const onKey = event => {
    if (event.key === 'Escape') close()
    if (event.key === 'Enter' && !closed) { event.preventDefault(); apply.click() }
  }
  const outside = event => { if (!node.contains(event.target)) close() }
  function close() {
    if (closed) return
    closed = true; node.remove()
    document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', outside)
    window.removeEventListener('nadoc:document-reset', close)
    if (active?.close === close) active = null
  }
  document.body.appendChild(node); sequence.focus()
  document.addEventListener('keydown', onKey); window.addEventListener('nadoc:document-reset', close)
  // Do not consume the click that opened this popup; cleanup also owns late setup.
  queueMicrotask(() => { if (!closed) document.addEventListener('mousedown', outside) })
  active = { close }; return active
}
