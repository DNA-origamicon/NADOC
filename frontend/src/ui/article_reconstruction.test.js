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
