/**
 * Regression: every NAMD MD job endpoint must carry the tab's X-NADOC-Doc header.
 *
 * The MD jobs panel previously used raw `fetch('/api/md/jobs…')` calls that omitted
 * the doc header, so they resolved the backend's DEFAULT document instead of the
 * tab's. The active-design staleness check then compared against the wrong design →
 * a spurious "the design has changed, can't continue" 409. Routing every MD call
 * through client.js (`_oxdnaJSON`, which always stamps `docHeaders()`) fixes it; this
 * test pins that the header is present so a future call can't silently drop it.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as api from './client.js'
import { getDocId } from '../shared/doc_id.js'
import { __resetForTests as resetPositioning } from '../ui/new_positioning.js'

const DOC = getDocId()   // jsdom main-app tab mints a sticky per-tab id

describe('MD client functions stamp X-NADOC-Doc', () => {
  let calls
  beforeEach(() => {
    resetPositioning(true)
    calls = []
    global.fetch = vi.fn(async (url, opts) => {
      calls.push({ url, opts })
      return { ok: true, status: 200, json: async () => ({ ok: true }) }
    })
  })

  it('has a doc id in this (non-editor) test context', () => {
    expect(DOC).toBeTruthy()
  })

  it('states the active display projection on API requests', async () => {
    await api.getDesign()
    expect(calls.at(-1).opts.headers['X-NADOC-Measured-Positioning']).toBe('true')
    resetPositioning(false)
    await api.getDesign()
    expect(calls.at(-1).opts.headers['X-NADOC-Measured-Positioning']).toBe('false')
  })

  it('sends the doc header on every MD job endpoint', async () => {
    await api.listMdJobs()
    await api.getMdJob('J1')
    await api.appendMdProduction('J1', { steps: 1000 })
    await api.startMdJob('J1')
    await api.stopMdJob('J1')
    await api.deleteMdJob('J1')
    await api.getMdDisplayMeta('J1')
    await api.getMdJobMetrics('J1')
    await api.getMdJobFixAdvice('J1')
    await api.refitMdJob('J1', {})
    await api.namdAvailable()
    await api.createMdJob({})

    expect(calls.length).toBe(12)
    for (const { url, opts } of calls) {
      expect(opts.headers['X-NADOC-Doc'], `missing doc header on ${url}`).toBe(DOC)
    }
  })

  it('stamps the continue-production call with method + body intact', async () => {
    await api.appendMdProduction('J1', { steps: 1000, continue_from_production: true })
    const prod = calls.find(c => c.url.endsWith('/md/jobs/J1/production'))
    expect(prod.opts.method).toBe('POST')
    expect(prod.opts.headers['X-NADOC-Doc']).toBe(DOC)
    expect(JSON.parse(prod.opts.body)).toMatchObject({ steps: 1000, continue_from_production: true })
  })

  it('returns null and records the detail on a 409 (the panel re-throws that message)', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false, status: 409, json: async () => ({ detail: 'A different design is loaded' }),
    }))
    const r = await api.appendMdProduction('J1', { steps: 1 })
    expect(r).toBe(null)
    expect(api.lastErrorMessage()).toBe('A different design is loaded')
  })
})
