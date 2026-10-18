import { createModal } from './primitives/modal.js'
import { createCpdContextPreview } from './cpd_context_preview.js'
import { el } from './primitives/dom.js'
export async function showCpdConversion({ api, baseKeys }) {
  const keys = [...baseKeys]
  const status = el('p', { text: 'Loading CPD isomers…', attrs: { role: 'status' } })
  const choices = el('select', { attrs: { 'aria-label': 'CPD type', style: 'width:100%;padding:8px;background:#202833;color:#e6edf3;border:1px solid #576574;border-radius:4px' } })
  const context = el('p')
  const host = el('div')
  const before = el('input', { attrs: { type: 'checkbox', 'aria-label': 'Show original thymines' } })
  const refresh = el('button', { text: 'Refresh preview', attrs: { type: 'button' } })
  const convert = el('button', { text: 'Convert to CPD', className: 'primary-btn', attrs: { disabled: true } })
  const body = el('div', { children: [choices, context, host,
    el('p', { text: 'Drag to rotate · scroll to zoom. Pink: new CPD bonds. Backbone colors identify strands.' }),
    el('label', { text: 'Show original thymines ', children: [before] }), refresh, status] })
  let epoch = 0, preview = null, viewer = null, saving = false, revision
  const modal = createModal({ title: 'Convert to CPD', size: 'lg', body, actions: [convert], onClose: () => {
    if (saving) return false
    epoch++; viewer?.dispose()
  } })
  modal.open()
  before.addEventListener('change', () => viewer?.setBefore(before.checked))
  async function select() {
    const token = ++epoch
    preview = null; convert.disabled = true
    status.textContent = 'Fitting isomer to selected thymines…'
    try {
      const result = await api.previewCpdConversion(keys, choices.value, revision)
      if (token !== epoch || !modal.isOpen()) return
      if (!result?.positions?.length) throw new Error('CPD context preview is unavailable.')
      revision = result.revision
      viewer ??= createCpdContextPreview(host)
      viewer.setData(result)
      preview = result
      context.textContent = `${result.relationship === 'same strand' ? 'Same strand' : 'Different strands'} · Endpoint 1: ${result.endpoints?.[0]?.key ?? keys[0]} · Endpoint 2: ${result.endpoints?.[1]?.key ?? keys[1]}`
      status.textContent = `${result.qualification} Sugar–base attachment lengths: ${result.glycosidic_distances_nm.map(n => (n * 10).toFixed(2)).join(' / ')} Å.`
      convert.disabled = false
    } catch (error) {
      if (token === epoch && modal.isOpen()) status.textContent = error.message
    }
  }
  choices.addEventListener('change', select)
  refresh.addEventListener('click', () => { if (!saving) { revision = undefined; void select() } })
  convert.addEventListener('click', async () => {
    if (!preview || saving) return
    saving = true; convert.disabled = true; choices.disabled = true; refresh.disabled = true
    status.textContent = preview.placement?.flanking_bases_fixed
      ? 'Applying six-residue geometry; flanking bases stay fixed…'
      : 'Converting bases; backbone stays fixed…'
    try {
      const result = await api.convertThyminesToCpd(keys, choices.value, revision)
      if (!result) throw new Error('Conversion failed. Check the current selection and try again.')
      saving = false; modal.close()
    } catch (error) {
      status.textContent = /design changed/i.test(error.message)
        ? 'Design changed. Refresh the preview before converting.' : error.message
      preview = null
    } finally {
      saving = false; convert.disabled = !preview; choices.disabled = false; refresh.disabled = false
    }
  })
  try {
    const catalog = await api.getCpdConversionOptions()
    if (!modal.isOpen()) return modal
    if (!catalog?.products?.length) throw new Error('CPD isomers could not be loaded.')
    for (const p of catalog.products) choices.append(el('option', { text: `${p.label} · MVP`, attrs: { value: p.stereochemistry } }))
    await select()
  } catch (error) {
    if (modal.isOpen()) status.textContent = error.message
  }
  return modal
}
