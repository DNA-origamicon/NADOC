// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { appendRestartNotice, restartSummary } from './alpine_restart_notice.js'
import { jobListSignature } from './jobs_panel_model.js'
import { mdRunControl } from './md_jobs_panel.js'

const event = () => ({ id: '123-r1', revision: 1, slurm_job_id: '123', restart_count: 1,
  mode: 'continued', acknowledged_at: null, segments: [{ segment: 'prod', mode: 'continued', checkpoint_step: 20000, timestep_fs: 4 }] })
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
function mount(acknowledge) {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.dispatchEvent(new Event('close')) }
  const row = document.createElement('div')
  document.body.append(row)
  appendRestartNotice(row, { jobId: 'abc', restartEvents: [event()] }, { acknowledge })
  return row.querySelector('button')
}
function byText(text) { return [...document.querySelectorAll('button')].find(b => b.textContent === text) }

describe('Alpine restart notice', () => {
  it('states continuation step and preserves seed-restart sampling caveat', () => {
    expect(restartSummary(event())).toContain('0.080 ns')
    expect(restartSummary({ mode: 'restarted' })).toContain('statistical independence is unverified')
  })
  it('closing does not acknowledge; explicit confirmation persists and clears the alert', async () => {
    const acknowledge = vi.fn().mockResolvedValue({ ok: true, restart_events: [{ ...event(), acknowledged_at: 123 }] })
    const button = mount(acknowledge)
    button.click()
    expect(document.querySelector('dialog').textContent).toContain('Resumed from checkpoint')
    byText('Close').click()
    expect(acknowledge).not.toHaveBeenCalled()
    expect(button.textContent).toBe('⚠')
    button.click()
    byText('I understand').click()
    await vi.waitFor(() => expect(button.textContent).toBe('ⓘ'))
    expect(acknowledge).toHaveBeenCalledWith('abc', [event()])
    expect(document.querySelector('dialog')).toBeNull()
    button.click()
    expect(byText('I understand')).toBeUndefined()
  })
  it('failed or stale acknowledgment leaves the alert visible', async () => {
    const button = mount(vi.fn().mockRejectedValue(new Error('Details changed')))
    button.click()
    byText('I understand').click()
    await vi.waitFor(() => expect(document.querySelector('[role=alert]').textContent).toBe('Details changed'))
    expect(button.textContent).toBe('⚠')
    expect(byText('I understand').disabled).toBe(false)
  })
  it('an acknowledgment changes the list signature and snapshots have no run action', () => {
    const job = { job_id:'abc', status:'running', restart_events:[event()] }
    const before = jobListSignature([job], {})
    job.restart_events[0].acknowledged_at = 123
    expect(jobListSignature([job], {})).not.toBe(before)
    expect(mdRunControl({ status:'stopped', restart_snapshot:true }).disabled).toBe(true)
  })
})
