/** Article screening owns no design state; input changes invalidate every verdict. */
import { createModal } from './primitives/modal.js'
import { showImageEvaluation } from './image_evaluation.js'
import './image_evaluation.css'
import { createArticleDesignSelection } from './article_design_selection.js'

const checks = [
  ['paper', 'Paper available or findable'],
  ['origami', 'DNA origami identified'],
  ['supplement', 'caDNAno diagram evidence in supplements'],
  ['detail', 'Image detail analysis'],
  ['reconstruction', 'Reconstruction feasibility and confidence'],
]
let active = null
const encode = file => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve({ name: file.name, data: reader.result.split(',')[1] })
  reader.onerror = () => reject(new Error('Could not read the selected PDF.'))
  reader.readAsDataURL(file)
})

export function showArticleReconstruction({ fetchImpl = globalThis.fetch } = {}) {
  if (active?.isOpen()) return active
  const body = document.createElement('div')
  body.className = 'article-reconstruction'
  body.innerHTML = `
    <p>Enter a DOI or upload the paper, then check the available reconstruction evidence.</p>
    <label>DOI <input data-doi type="text" placeholder="10.… or https://doi.org/…"></label>
    <label>Paper PDF <input data-paper type="file" accept="application/pdf,.pdf"></label>
    <label>Supplement PDFs (up to two) <input data-supplements type="file" accept="application/pdf,.pdf" multiple></label>
    <label>Staple lists <input data-staple-lists type="file" accept=".xlsx,.xls,.csv,.json,.txt" multiple></label>
    <label>Scaffold sequence (optional; default M13mp18 hypothesis)<textarea data-scaffold rows="2" placeholder="ACGT…"></textarea></label>
    <p>Up to 100 pages per PDF. DOI lookup checks available metadata and open-access text. Upload PDFs when the paper or supplement cannot be accessed. caDNAno files are not required.</p>
    <div class="ie-toolbar"><button data-check>Check</button><button data-cancel disabled>Cancel</button></div>
    <p>Basic screening accepts diagram captions or labels. Use Detect designs for image/list pairing and direction hypotheses. Select a detected design and its endpoint table to reconstruct. Partial results include a report of missing or ambiguous routes.</p>
    <ol data-checks aria-live="polite"></ol>
    <p data-status role="status">Ready to check.</p>
    <div class="ie-toolbar"><button data-reconstruct title="Select a detected figure and endpoint table" disabled>Reconstruct</button><button data-evidence>Inspect diagram evidence…</button></div>`
  const q = selector => body.querySelector(selector)
  let controller = null, revision = 0
  const readPayload = async () => {
    const paper = q('[data-paper]').files?.[0]
    return { doi: q('[data-doi]').value.trim(), paper: paper ? await encode(paper) : null,
      supplements: await Promise.all(Array.from(q('[data-supplements]').files || []).map(encode)),
      staple_lists: await Promise.all(Array.from(q('[data-staple-lists]').files || []).map(encode)),
      scaffold_sequence: q('[data-scaffold]').value.trim() }
  }
  const analysis = createArticleDesignSelection({ body, fetchImpl, readPayload,
    onSelectionChange: selections => { q('[data-reconstruct]').disabled = !selections.length } })
  const rows = new Map()
  for (const [id, label] of checks) {
    const row = document.createElement('li')
    const title = document.createElement('strong'), detail = document.createElement('p')
    row.append(title, detail); q('[data-checks]').append(row)
    rows.set(id, { row, title, detail, label })
  }
  function reset() {
    revision++; controller?.abort(); controller = null; analysis.reset()
    for (const [id, { row, title, detail, label }] of rows) {
      const deferred = ['detail', 'reconstruction'].includes(id)
      row.dataset.state = deferred ? 'deferred' : 'pending'; title.textContent = `○ ${label}`; detail.textContent = id === 'detail' ? 'Run Detect designs' : deferred ? 'Run Detect designs' : 'Not checked'
    }
    q('[data-check]').disabled = false; q('[data-cancel]').disabled = true
    q('[data-reconstruct]').disabled = true
  }
  const modal = createModal({ title: 'Reconstruct from Article', size: 'lg', body,
    onClose: () => { revision++; controller?.abort(); analysis.dispose(); active = null } })
  active = modal; reset()
  for (const selector of ['[data-doi]', '[data-paper]', '[data-supplements]', '[data-staple-lists]', '[data-scaffold]']) {
    q(selector).addEventListener('input', () => { reset(); q('[data-status]').textContent = 'Inputs changed. Click Check to recheck.' })
  }
  q('[data-cancel]').addEventListener('click', () => { reset(); q('[data-status]').textContent = 'Check canceled.' })
  q('[data-reconstruct]').addEventListener('click', async () => {
    const current = revision
    const selections = analysis.selectedReconstructions()
    if (!selections.length) return
    q('[data-reconstruct]').disabled = true
    q('[data-status]').textContent = 'Reconstructing native designs and verifying recorded history… This may take several minutes.'
    try {
      const payload = { ...await readPayload(), selections }
      if (current !== revision) return
      const response = await fetchImpl('/api/article-reconstruction/reconstruct', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Reconstruction failed.') }
      const blob = await response.blob()
      if (current !== revision) return
      const url = URL.createObjectURL(blob), link = document.createElement('a')
      link.href = url; link.download = 'reconstructed-designs.zip'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      q('[data-status]').textContent = 'Downloaded reconstruction package. Read each report for missing or ambiguous routes, then open its .nadoc file. If construction could not pass validation, the package contains its report without a design.'
    } catch (error) {
      if (current === revision) q('[data-status]').textContent = error.message
    } finally {
      if (current === revision) q('[data-reconstruct]').disabled = !analysis.selectedReconstructions().length
    }
  })
  q('[data-evidence]').addEventListener('click', () => showImageEvaluation({ fetchImpl }))
  q('[data-check]').addEventListener('click', async () => {
    reset()
    const current = revision
    const paper = q('[data-paper]').files?.[0]
    const supplements = Array.from(q('[data-supplements]').files || [])
    const doi = q('[data-doi]').value.trim()
    if (!doi && !paper) { q('[data-status]').textContent = 'Enter a DOI or upload a paper PDF.'; return }
    if (supplements.length > 2) {
      q('[data-status]').textContent = 'Use up to two supplement PDFs.'; return
    }
    controller = new AbortController()
    const signal = controller.signal
    q('[data-check]').disabled = true; q('[data-cancel]').disabled = false
    q('[data-status]').textContent = 'Checking article evidence…'
    try {
      const payload = { doi, paper: paper ? await encode(paper) : null, supplements: await Promise.all(supplements.map(encode)) }
      if (current !== revision) return
      const response = await fetchImpl('/api/article-reconstruction/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal })
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Article check failed.') }
      const reader = response.body.getReader(), decoder = new TextDecoder()
      let buffer = '', completed = false
      while (true) {
        const { value, done } = await reader.read()
        if (current !== revision) { await reader.cancel(); return }
        buffer += decoder.decode(value, { stream: !done })
        const lines = buffer.split('\n'); buffer = lines.pop()
        for (const line of lines) {
          if (!line.trim()) continue
          const item = JSON.parse(line)
          if (item.type === 'complete') {
            completed = true
            q('[data-status]').textContent = item.ready_for_analysis
              ? 'Checks complete. Basic evidence is sufficient to proceed to image analysis.'
              : 'Checks complete. See missing or inaccessible evidence above. Use Detect designs to inspect available image and sequence evidence.'
          } else if (rows.has(item.id)) {
            const { row, title, detail, label } = rows.get(item.id)
            row.dataset.state = item.status
            title.textContent = `${{ passed: '✓', failed: '✗', running: '…', deferred: '○' }[item.status] || '○'} ${label}`
            detail.textContent = item.detail
          }
        }
        if (done) break
      }
      if (!completed) throw new Error('Check interrupted before completion. Please retry.')
    } catch (error) {
      if (current === revision) {
        q('[data-status]').textContent = error.name === 'AbortError' ? 'Check canceled.' : error.message
        for (const { row, title, detail, label } of rows.values()) if (row.dataset.state === 'running') {
          row.dataset.state = 'failed'; title.textContent = `✗ ${label}`; detail.textContent = 'Check interrupted.'
        }
      }
    } finally {
      if (current === revision) { q('[data-check]').disabled = false; q('[data-cancel]').disabled = true }
    }
  })
  modal.open(); return modal
}
