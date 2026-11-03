import { describe, expect, it, vi } from 'vitest'
import { createAssetOperationRequests } from './asset_operation_requests.js'
import { createAssetSaveCoordination } from './asset_save_coordination.js'

function harness() {
  let revision = 7
  let state = { currentDesign: { id: 'part', feature_log: [{ id: 'feature' }] } }
  const subscribers = new Set(), store = { getState: () => state,
    subscribe: fn => { subscribers.add(fn); return () => subscribers.delete(fn) },
    setState: patch => { state = { ...state, ...patch }; subscribers.forEach(fn => fn()) } }
  const receipt = { job_id: 'job', status: 'committed', revision: 8, design_id: 'part' }
  const result = { design: { id: 'part' }, revision: 8 }
  const ready = { job_id: 'job', status: 'complete', stale: false, source_busy: false,
    result: { status: 'ready', append: { nanoparticle_id: 'gold' } } }
  const transport = { start: vi.fn(async () => ({ job_id: 'job', source_revision: 7 })),
    poll: vi.fn(async () => ready), cancel: vi.fn(async () => ({})),
    commit: vi.fn(async () => receipt), refreshCommitted: vi.fn(async () => result),
    apply: vi.fn(async value => store.setState({ currentDesign: value.design })) }
  const request = vi.fn(async () => ({ job_id: 'job', source_revision: 7 }))
  const saves = createAssetSaveCoordination()
  const view = { update: vi.fn(), close: vi.fn() }, showProgress = vi.fn(() => view)
  const api = createAssetOperationRequests({ store, request, transport, getDocId: () => 'doc',
    currentRevision: () => revision, documentRequests: { capture: () => 1, isCurrent: () => true },
    syncDesign: transport.apply, showProgress, saves, pollMs: 0, events: new EventTarget() })
  return { api, transport, request, store, showProgress, view, subscribers, receipt, ready,
    setRevision: value => { revision = value }, saves }
}
const run = h => h.api.ordinary('POST', '/design/nanoparticles/gold/biotin-dna', { sequence: 'ACGT' })

describe('ordinary asset transactions', () => {
  it('holds autosave through editing and preserves refresh ownership after the editor closes', async () => {
    const h = harness(), context = await h.api.beginEdit(), save = vi.fn()
    const deferred = h.saves.save(save, () => true)
    await Promise.resolve()
    expect(save).not.toHaveBeenCalled()
    h.transport.refreshCommitted.mockRejectedValueOnce(new Error('Offline'))
    await expect(h.api.edit(0, {}, context, 'feature')).rejects.toThrow('Offline')
    h.api.endEdit(context)
    expect(save).not.toHaveBeenCalled()
    await h.view.update.mock.calls.at(-1)[1].refresh()
    await deferred
    expect(save).toHaveBeenCalledTimes(1)
  })
  it('publishes once, refreshes privately, adopts once, and releases listeners', async () => {
    const h = harness()
    expect((await run(h)).nanoparticle_id).toBe('gold')
    expect(h.request.mock.calls[0][1]).toContain('expected_revision=7&expected_design_id=part')
    expect(h.transport.commit).toHaveBeenCalledTimes(1)
    expect(h.transport.apply).toHaveBeenCalledTimes(1)
    expect(h.transport.cancel).not.toHaveBeenCalled()
    expect(h.view.close).toHaveBeenCalledTimes(1)
    expect(h.subscribers.size).toBe(0)
  })
  it('cancels a private job without applying or publishing', async () => {
    const h = harness()
    h.transport.poll.mockImplementation(async () => {
      h.showProgress.mock.calls[0][0].cancel()
      return h.ready
    })
    await expect(run(h)).rejects.toMatchObject({ name: 'AbortError' })
    expect(h.transport.cancel).toHaveBeenCalled()
    expect(h.transport.commit).not.toHaveBeenCalled()
    expect(h.transport.apply).not.toHaveBeenCalled()
    expect(h.subscribers.size).toBe(0)
  })
  it('discards a delayed start reply after switching documents', async () => {
    const h = harness()
    h.request.mockImplementation(async () => {
      h.store.setState({ currentDesign: { id: 'other' } })
      return { job_id: 'job', source_revision: 7 }
    })
    await expect(run(h)).rejects.toThrow()
    expect(h.transport.cancel).toHaveBeenCalledWith('job', expect.anything())
    expect(h.transport.apply).not.toHaveBeenCalled()
    expect(h.showProgress).not.toHaveBeenCalled()
  })
  it('continues across a metadata refresh with the same authoring revision and loadout', async () => {
    const h = harness()
    h.request.mockImplementation(async () => {
      h.store.setState({ currentDesign: { ...h.store.getState().currentDesign, metadata: { identity_confirmed_at: 'now' } } })
      return { job_id: 'job', source_revision: 7 }
    })
    await run(h)
    expect(h.transport.apply).toHaveBeenCalledTimes(1)
    expect(h.transport.cancel).not.toHaveBeenCalled()
  })
  it('recovers a lost commit reply by observing the same job', async () => {
    const h = harness()
    h.transport.commit.mockRejectedValue(new Error('Connection lost'))
    h.transport.poll.mockResolvedValueOnce(h.ready).mockResolvedValue({ ...h.receipt, stale: false, source_busy: false })
    await run(h)
    expect(h.request).toHaveBeenCalledTimes(1)
    expect(h.transport.commit).toHaveBeenCalledTimes(1)
    expect(h.transport.apply).toHaveBeenCalledTimes(1)
  })
  it('confirms its own publication when a background read adopts the new revision first', async () => {
    const h = harness()
    h.transport.commit.mockImplementation(async () => {
      h.setRevision(8)
      h.store.setState({ currentDesign: { id: 'part' } })
      return h.receipt
    })
    await run(h)
    expect(h.transport.refreshCommitted).toHaveBeenCalledTimes(1)
    expect(h.transport.apply).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ revision: 8 }))
    expect(h.transport.cancel).not.toHaveBeenCalled()
  })
  it('cannot adopt another edit that wins the publication race', async () => {
    const h = harness(), winner = { id: 'part', metadata: { name: 'Other edit' } }
    h.transport.commit.mockImplementation(async () => {
      h.setRevision(8); h.store.setState({ currentDesign: winner })
      throw Object.assign(new Error('Source changed'), { status: 409 })
    })
    await expect(run(h)).rejects.toThrow('Source changed')
    expect(h.transport.apply).not.toHaveBeenCalled()
    expect(h.transport.refreshCommitted).not.toHaveBeenCalled()
    expect(h.store.getState().currentDesign).toBe(winner)
  })
  it('retains refresh recovery and blocks duplicate intent when publication is uncertain', async () => {
    const h = harness()
    h.transport.refreshCommitted.mockRejectedValueOnce(new Error('Offline'))
    await expect(run(h)).rejects.toThrow('Offline')
    await expect(run(h)).rejects.toThrow('Finish or refresh')
    const options = h.view.update.mock.calls.at(-1)[1]
    expect(options.committing).toBe(true)
    await options.refresh()
    expect(h.transport.commit).toHaveBeenCalledTimes(1)
    expect(h.transport.apply).toHaveBeenCalledTimes(1)
    expect(h.subscribers.size).toBe(0)
  })
  it('attributes a failed historical edit and preserves the current document', async () => {
    const h = harness(), context = h.api.capture()
    h.transport.poll.mockResolvedValue({ ...h.ready, result: { status: 'failed', issues: [{
      code: 'missing_reference', detail: 'Handle removed', feature_id: 'feature' }] } })
    await expect(h.api.edit(0, { sequence: 'ACGA' }, context, 'feature')).rejects.toThrow('Handle removed')
    expect(h.transport.commit).not.toHaveBeenCalled()
    expect(h.store.getState().currentDesign).toBe(context.source)
  })
  it('names the downstream row in the worker HTTP-error envelope', async () => {
    const h = harness(), context = h.api.capture()
    context.source.feature_log.push({ id: 'biotin', feature_type: 'snapshot', label: 'Biotinylated DNA' })
    h.transport.poll.mockResolvedValue({ ...h.ready, result: { status: 'failed', issues: [{
      code: 'evaluation_rejected', http_status: 409,
      detail: { code: 'invalid_selection', detail: 'Coating site count changed', feature_id: 'biotin' } }] } })
    await expect(h.api.edit(0, {}, context, 'feature')).rejects.toThrow('F2 Biotinylated DNA cannot regenerate')
    expect(h.transport.commit).not.toHaveBeenCalled()
  })
  it('guards protected parts, old cursors, and a replaced selected feature before dispatch', async () => {
    const h = harness(), source = h.store.getState().currentDesign
    source.feature_log_cursor = 0
    await expect(run(h)).rejects.toThrow('current editable part')
    source.feature_log_cursor = -1
    source.active_loadout_id = 'a'; source.loadouts = [{ id: 'a', protected: true }]
    await expect(run(h)).rejects.toThrow('current editable part')
    await expect(h.api.edit(0, {}, h.api.capture(), 'different')).rejects.toThrow('part changed')
    expect(h.request).not.toHaveBeenCalled()
  })
})
