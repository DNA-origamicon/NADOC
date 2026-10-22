import { describe, it, expect, vi, afterEach } from 'vitest'
import { openThinJob, THIN_JOB_CONFIRMATION } from './md_thin_job.js'
const preview = { fingerprint: 'snapshot', source_frames: 1000, file_count: 1,
  rmsd_note: 'Sampled aligned DNA heavy atoms.', boundary_note: 'First frame in each segment.',
  options: [1, 2, 4, 5, 10].map(stride => ({ stride, spacing_ps: [20 * stride],
    saved_bytes: 1000000 * (1 - 1 / stride), saved_percent: 100 * (1 - 1 / stride), median_rmsd_A: 1.6 })),
}
const button = label => [...document.querySelectorAll('button')].find(b => b.textContent === label)
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
const make = () => ({ previewThinMdJob: vi.fn().mockResolvedValue(preview), applyThinMdJob: vi.fn().mockResolvedValue({ ok: true, saved_bytes: 500000 }) })
afterEach(() => { document.body.innerHTML = '' })
describe('Thin job dialog', () => {
  it('shows the measured table and Cancel never mutates', async () => {
    const api = make(); const modal = openThinJob({ jobId: 'j', api }); await modal.ready
    expect(document.querySelectorAll('tbody tr')).toHaveLength(5)
    expect(document.querySelector('table').textContent).toContain('40 ps')
    expect(document.querySelector('table').textContent).toContain('1.60 Å')
    expect(document.querySelector('select').value).toBe('2')
    button('Cancel').click(); expect(api.applyThinMdJob).not.toHaveBeenCalled(); expect(modal.isOpen()).toBe(false)
  })
  it('requires separate Yes confirmation and respects No and the selected interval', async () => {
    const api = make(); const onApplied = vi.fn(); const onApplying = vi.fn()
    const modal = openThinJob({ jobId: 'j', api, onApplied, onApplying }); await modal.ready
    const select = document.querySelector('select'); select.value = '5'; select.dispatchEvent(new Event('change'))
    button('Apply').click(); await settle()
    expect(document.querySelectorAll('[role=dialog]')).toHaveLength(2)
    expect(document.body.textContent).toContain(THIN_JOB_CONFIRMATION)
    expect(api.applyThinMdJob).not.toHaveBeenCalled()
    button('No').click(); await settle(); expect(api.applyThinMdJob).not.toHaveBeenCalled()
    expect(modal.isOpen()).toBe(true)
    button('Apply').click(); await settle(); button('Yes').click(); await settle()
    expect(onApplying).toHaveBeenCalledOnce()
    expect(api.applyThinMdJob).toHaveBeenCalledExactlyOnceWith('j', { stride: 5, fingerprint: 'snapshot', confirmed: true })
    expect(onApplied).toHaveBeenCalledOnce(); expect(modal.isOpen()).toBe(false)
  })
  it('disables Apply for unchanged data, during loading, and after stale-preview rejection', async () => {
    const api = make(); api.applyThinMdJob.mockResolvedValue(null); api.lastErrorMessage = () => 'Job files changed since preview.'
    const modal = openThinJob({ jobId: 'j', api }); expect(button('Apply').disabled).toBe(true); await modal.ready
    const select = document.querySelector('select'); select.value = '1'; select.dispatchEvent(new Event('change'))
    expect(button('Apply').disabled).toBe(true)
    select.value = '2'; select.dispatchEvent(new Event('change'))
    button('Apply').click(); await settle(); button('Yes').click(); await settle()
    expect(document.body.textContent).toContain('Job files changed'); expect(button('Apply').disabled).toBe(true); modal.close()
  })
  it('prevents double submission and dismissal while applying', async () => {
    const api = make(); let complete; api.applyThinMdJob.mockReturnValue(new Promise(r => { complete = r }))
    const modal = openThinJob({ jobId: 'j', api }); await modal.ready
    button('Apply').click(); await settle(); button('Yes').click(); await settle(); button('Apply').click()
    modal.close(); expect(modal.isOpen()).toBe(true); expect(api.applyThinMdJob).toHaveBeenCalledOnce()
    complete({ ok: true }); await settle(); expect(modal.isOpen()).toBe(false)
  })
  it('closing during assessment cannot apply or reopen later', async () => {
    const api = make(); let finish; api.previewThinMdJob.mockReturnValue(new Promise(r => { finish = r }))
    const modal = openThinJob({ jobId: 'j', api }); button('Cancel').click(); finish(preview); await modal.ready
    expect(modal.isOpen()).toBe(false); expect(api.applyThinMdJob).not.toHaveBeenCalled()
  })
})
