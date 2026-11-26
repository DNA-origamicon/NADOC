import { afterEach, expect, it, vi } from 'vitest'
import { showArticleReconstruction } from './article_reconstruction.js'
let modal
const q = s => document.querySelector(s)
afterEach(() => { modal?.close(); document.body.replaceChildren() })
it('requires a source and opens only one dialog', () => {
  const fetchImpl = vi.fn()
  modal = showArticleReconstruction({ fetchImpl })
  expect(showArticleReconstruction()).toBe(modal)
  q('[data-check]').click()
  expect(q('[data-status]').textContent).toContain('Enter a DOI')
  expect(fetchImpl).not.toHaveBeenCalled()
  expect(q('[data-reconstruct]').disabled).toBe(true)
})
it('renders streamed results and invalidates them when inputs change', async () => {
  const lines = [
    { id: 'paper', status: 'running', detail: 'Looking up DOI' },
    { id: 'paper', status: 'passed', detail: 'Paper found' },
    { id: 'reconstruction', status: 'deferred', detail: 'Later stage: reconstruction confidence' },
    { type: 'complete', can_reconstruct: false, ready_for_analysis: true },
  ].map(item => JSON.stringify(item) + '\n').join('')
  const bytes = new TextEncoder().encode(lines)
  let index = 0
  const chunks = [bytes.slice(0, 17), bytes.slice(17)]
  const fetchImpl = vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => index < chunks.length ? { value: chunks[index++], done: false } : { done: true } }) } })
  modal = showArticleReconstruction({ fetchImpl })
  q('[data-doi]').value = '10.1234/test'; q('[data-check]').click()
  await vi.waitFor(() => expect(q('[data-status]').textContent).toContain('Checks complete'))
  expect(q('[data-checks]').textContent).toContain('✓ Paper')
  expect(q('[data-checks]').textContent).toContain('Later stage: reconstruction confidence')
  expect(q('[data-reconstruct]').disabled).toBe(true)
  expect(q('[data-status]').textContent).toContain('sufficient to proceed to image analysis')
  q('[data-doi]').dispatchEvent(new Event('input'))
  expect(document.querySelectorAll('[data-state="pending"]')).toHaveLength(3)
})
it('cancels and ignores a late response', async () => {
  let resolve
  const fetchImpl = vi.fn(() => new Promise(r => { resolve = r }))
  modal = showArticleReconstruction({ fetchImpl })
  q('[data-doi]').value = '10.1234/test'; q('[data-check]').click()
  await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce())
  q('[data-cancel]').click()
  expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true)
  resolve({ ok: false, json: async () => ({ detail: 'late failure' }) })
  await Promise.resolve(); await Promise.resolve()
  expect(q('[data-status]').textContent).toBe('Check canceled.')
})
it('enables native reconstruction only for a selected figure/table and downloads its report package', async () => {
  const report = { designs: [{ id: 'd', label: 'D009', source_sha256: 'abc', page: 6, image: '', context: '', rows: 46, branches: 0, observed_paths: [], route_hypotheses_tested: 1, limitations: [], pairings: [{ list_id: 't', label: 'table', list_rows: 197, basis: 'endpoints', alternatives: [], publication_evidence: { table_page: 14 } }] }], staple_lists: [], notes: [] }
  const fetchImpl = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => report }).mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['zip']) })
  const create = vi.fn(() => 'blob:test'), revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  try {
    modal = showArticleReconstruction({ fetchImpl })
    q('[data-analyze]').click()
    await vi.waitFor(() => expect(q('.article-design-card select')).not.toBeNull())
    q('[data-design-id]').click()
    expect(q('[data-reconstruct]').disabled).toBe(true)
    q('.article-design-card select').value = 't'; q('.article-design-card select').dispatchEvent(new Event('change'))
    expect(q('[data-reconstruct]').disabled).toBe(false)
    q('[data-reconstruct]').click()
    await vi.waitFor(() => expect(click).toHaveBeenCalledOnce())
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body).selections).toEqual([{ source_sha256: 'abc', diagram_page: 6, table_page: 14 }])
    expect(q('[data-status]').textContent).toContain('missing or ambiguous routes')
    await new Promise(resolve => setTimeout(resolve, 1050))
    expect(revoke).toHaveBeenCalledWith('blob:test')
  } finally { click.mockRestore(); vi.unstubAllGlobals() }
})
