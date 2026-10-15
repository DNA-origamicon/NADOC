// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { buildJobRowModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobRow } from './jobs_panel_render.js'

const job = { job_id: 'frozen-job', status: 'completed', out_of_date: false, created_at: 1 }
const context = { engine: 'oxdna', isStale: value => !!value.out_of_date }

describe('physical input evidence in shared simulation rows', () => {
  it.each(['oxdna', 'namd'])('keeps matching legacy %s inputs explicitly unverified', engine => {
    const value = { ...job, input_freshness: { status: 'unknown', model_match: true, coverage: { complete: false } } }
    const before = JSON.stringify(value)
    const model = buildJobRowModel(value, { ...context, engine })
    const row = renderJobRow(model)
    expect(row.querySelector('.job-input-freshness')?.textContent).toBe('Inputs unverified')
    expect(row.querySelector('.job-input-freshness')?.title).toMatch(/partial model matches/)
    expect(model.stale).toBe(false)
    expect(model.statusKey).toBe('completed')
    expect(row.querySelector('button')).toBeNull()
    expect(JSON.stringify(value)).toBe(before)
  })

  it.each([undefined, null])('leaves older engine responses without evidence labels', input_freshness => {
    expect(renderJobRow(buildJobRowModel({ ...job, input_freshness }, context)).querySelector('.job-input-freshness')).toBeNull()
  })

  it.each([
    [{ status: 'stale' }, 'Inputs changed'],
    [{ status: 'unknown' }, 'Inputs unverified'],
    [{ status: 'current', coverage: { complete: false } }, 'Inputs unverified'],
    [{ status: 'current', coverage: { complete: true } }, 'Inputs match'],
    [{ status: '<img src=x onerror=alert(1)>' }, 'Inputs unverified'],
  ])('separates evidence from a completed run: %j', (input_freshness, label) => {
    const row = renderJobRow(buildJobRowModel({ ...job, input_freshness }, context))
    expect(row.querySelector('.job-input-freshness')?.textContent).toBe(label)
    expect(row.querySelector('img')).toBeNull()
  })

  it('retains the existing warning action alongside unknown input evidence', () => {
    const onWarning = vi.fn()
    const model = buildJobRowModel({ ...job, out_of_date: true, input_freshness: { status: 'unknown' } }, context)
    const row = renderJobRow(model, { onWarning })
    expect(row.querySelector('.job-input-freshness')?.textContent).toBe('Inputs unverified')
    row.querySelector('button').click()
    expect(onWarning).toHaveBeenCalledWith(job.job_id)
  })

  it('refreshes changed evidence but keeps unchanged polling stable', () => {
    const ctx = { ...context, rowSig: value => value.job_id }
    const unknown = { ...job, input_freshness: { status: 'unknown', model_match: null } }
    const partial = { ...unknown, input_freshness: { status: 'unknown', model_match: true } }
    const stale = { ...unknown, input_freshness: { status: 'stale' } }
    const signature = value => jobListSignature([value], ctx)
    expect(signature(unknown)).not.toBe(signature(job))
    expect(signature(partial)).not.toBe(signature(unknown))
    expect(signature(stale)).not.toBe(signature(partial))
    expect(signature({ ...partial, live_metrics: { step: 10 } })).toBe(signature(partial))
  })
})
