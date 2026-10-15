import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initPartRepairPanel, focusPartRepairRow } from './part_repair_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { RepairRequestError } from '../api/part_repair_endpoints.js'

const change = { action: 'set_input', feature_id: 'import', child_id: null,
  parameter_path: ['name'], expected_old: 'Original', value: 'Renamed' }
const saved = () => ({ version: 1, draft_id: 'draft', generation: 0, actions: [change] })
const source = { version: 1, sha256: 'a'.repeat(64), size_bytes: 3, format: 'pdb', media_type: 'chemical/x-pdb' }
const nameField = { parameter_path: ['name'], expected_old: 'Original', input_type: 'string', label: 'Name', max_length: 100 }
const sourceField = { parameter_path: ['source'], expected_old: source, input_type: 'source', label: 'Protein source',
  source_binding: { source, parameter: 'source', max_size_bytes: 300, replacement_supported: true } }
const panels = []
const flush = async () => { for (let index = 0; index < 20; index++) await Promise.resolve() }
const button = text => [...document.querySelectorAll('button')].find(item => item.textContent === text)
const click = async text => { const found = button(text); expect(found, text).toBeTruthy(); found.click(); await flush() }
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

function setup({ draft = null, protectedLoadout = false, fields = [nameField], featureLog, cursor = -1 } = {}) {
  let revision = 4, nextJob = 0
  const store = createMockStore({ currentDesign: { id: 'part', active_loadout_id: 'main',
    loadouts: [{ id: 'main', protected: protectedLoadout }], feature_log_cursor: cursor,
    feature_log: featureLog ?? [{ id: 'import', feature_type: 'snapshot', op_kind: 'protein-import', label: 'Import', params: { name: 'Original' } }],
    helices: { last_good: { unchanged: true } } }, assemblyActive: false, repairMetadata: null })
  const metadata = () => ({ design_id: 'part', revision, draft,
    repair_draft: draft ? { draft_id: draft.draft_id, generation: draft.generation, status: 'pending' } : null })
  const endpoints = {
    inspect: vi.fn(async () => metadata()),
    inspectInputs: vi.fn(async body => ({ version: 1, assessment: 'inputs_only', references_checked: false,
      design_id: 'part', revision, feature_id: body.feature_id, child_id: body.child_id, definition_supported: true, fields })),
    acknowledge: vi.fn(json => { revision = json.revision; store.setState({ repairMetadata: { designId: 'part', revision, summary: json.repair_draft } }); return true }),
    mutate: vi.fn(async body => {
      draft = body.operation === 'discard' ? null : { ...(draft ?? saved()),
        generation: body.operation === 'create' ? 0 : draft.generation + 1, actions: body.actions ?? draft.actions }
      return { ...metadata(), revision: revision + 1 }
    }),
    evaluate: vi.fn(async body => ({ job_id: `job-${++nextJob}`, status: 'running',
      repair_draft: { draft_id: body.expected_draft_id, generation: body.expected_generation } })),
    start: vi.fn(async () => ({ job_id: `job-${++nextJob}`, status: 'running' })),
    poll: vi.fn(async () => ({ status: 'running', result: null })),
    cancel: vi.fn(async () => ({})),
    commit: vi.fn(async id => ({ job_id: id, status: 'committed', design_id: 'part', revision: revision + 1 })),
    refreshCommitted: vi.fn(async receipt => ({ design: { ...store.getState().currentDesign,
      helices: { regenerated: true } }, revision: receipt.revision, nucleotides: [], helix_axes: [] })),
    apply: vi.fn(async json => { revision = json.revision; store.setState({ currentDesign: json.design }) }),
    inspectSource: vi.fn(async body => ({ ...body, expected_blob: { state: 'missing' } })),
    uploadSource: vi.fn(async () => ({ ...metadata(), revision: revision + 1,
      repair_draft: { ...metadata().repair_draft, base_status: 'rebase_required' }, published_source_changed: true })),
  }
  const host = document.createElement('div'); document.body.append(host)
  const focusFeature = vi.fn()
  const panel = initPartRepairPanel({ store, api: { partRepairAPI: endpoints, currentRevisionWatermark: () => revision }, host,
    getDocumentId: () => 'document', focusFeature })
  panels.push(panel)
  return { panel, store, endpoints, focusFeature, host, revision: () => revision }
}
async function open(h) { h.panel.open(); await flush() }
async function select(feature_id = 'import', child_id = null) {
  const selector = document.querySelector('[aria-label="Feature to repair"]')
  selector.value = JSON.stringify([feature_id, child_id]); selector.dispatchEvent(new Event('change')); await flush()
}
async function evaluateReady(h) {
  await click('Evaluate proposal')
  h.endpoints.poll.mockResolvedValue({ status: 'complete', stale: false, result: { status: 'ready',
    repair: { authoring_changes: { changed_fields: ['protein_assets'] } } } })
  await h.panel.controller.poll()
}
beforeEach(() => vi.useFakeTimers())
afterEach(() => { for (const panel of panels.splice(0)) panel.dispose(); document.body.replaceChildren(); vi.useRealTimers() })

describe('desktop part recipe repair panel', () => {
  it('requests nothing on mount and saves, evaluates and explicitly applies a typed proposal', async () => {
    const h = setup(), original = h.store.getState().currentDesign
    expect(h.endpoints.inspect).not.toHaveBeenCalled(); expect(h.endpoints.start).not.toHaveBeenCalled()
    await open(h)
    expect(document.querySelector('[role=status]').textContent).toContain('not checked')
    await select()
    const input = document.querySelector('[aria-label=Name]'); input.value = 'Renamed'
    await click('Add proposed change'); await click('Save proposal')
    expect(h.endpoints.mutate.mock.calls[0][0]).toMatchObject({ operation: 'create', expected_revision: 4,
      expected_design_id: 'part', actions: [change] })
    expect(h.store.getState().currentDesign).toBe(original)
    expect(h.revision()).toBe(5)
    await evaluateReady(h)
    expect(h.endpoints.apply).not.toHaveBeenCalled()
    expect(document.querySelector('.part-repair__muted').textContent).toBeTruthy()
    expect(document.body.textContent).toContain('Visual comparison is not available')
    expect(button('Apply evaluated proposal').disabled).toBe(false)
    await click('Apply evaluated proposal')
    expect(h.endpoints.commit).toHaveBeenCalledTimes(1); expect(h.endpoints.apply).toHaveBeenCalledTimes(1)
    expect(h.panel.controller.getState().draft.draft_id).toBe('draft')
    expect(button('Apply evaluated proposal').disabled).toBe(true)
    expect(h.store.getState().currentDesign.helices).toEqual({ regenerated: true })
  })

  it('selects a typed failing routing child without seeking recovery geometry', async () => {
    const h = setup({ featureLog: [{ id: 'group', feature_type: 'routing-cluster', children: [
      { id: 'child', feature_type: 'minor-mutation', op_subtype: 'protein-import', label: 'Import child' }] }] })
    await open(h); await click('Check published recipe')
    h.endpoints.poll.mockResolvedValue({ status: 'complete', result: { status: 'failed', issues: [
      { code: 'missing_reference', detail: 'Input is missing', feature_id: 'child', parameter_path: ['name'] }] } })
    await h.panel.controller.poll(); await click('Inspect failing input')
    expect(h.endpoints.inspectInputs).toHaveBeenCalledWith(expect.objectContaining({ feature_id: 'group', child_id: 'child' }), expect.anything())
    expect(h.focusFeature).toHaveBeenCalledWith(expect.objectContaining({ featureId: 'group', childId: 'child', subIndex: 0 }))
    expect(document.activeElement.dataset.repairPath).toBe('["name"]')
    expect(h.store.getState().currentDesign.feature_log_cursor).toBe(-1)
    expect(h.endpoints.apply).not.toHaveBeenCalled()
  })

  it('distinguishes publication from a failed display refresh and retries only that read', async () => {
    const h = setup({ draft: saved() }), original = h.store.getState().currentDesign
    await open(h); await evaluateReady(h)
    h.endpoints.refreshCommitted.mockRejectedValueOnce(new Error('Display unavailable'))
    await click('Apply evaluated proposal')
    expect(document.querySelector('[role=status]').textContent).toContain('published at revision 5; display refresh is still needed')
    expect(h.store.getState().currentDesign).toBe(original)
    expect(button('Apply evaluated proposal').disabled).toBe(true)
    expect(button('Evaluate proposal').disabled).toBe(true)
    expect(button('Refresh committed result').hidden).toBe(false)
    await click('Refresh committed result')
    expect(h.endpoints.commit).toHaveBeenCalledTimes(1)
    expect(h.endpoints.refreshCommitted).toHaveBeenCalledTimes(2)
    expect(h.endpoints.apply).toHaveBeenCalledTimes(1)
    expect(h.endpoints.cancel).not.toHaveBeenCalled()
    expect(button('Refresh committed result').hidden).toBe(true)
  })

  it('shows an unknown publication outcome after a lost receipt and resolves without a second commit', async () => {
    const h = setup({ draft: saved() }); await open(h); await evaluateReady(h)
    h.endpoints.commit.mockRejectedValueOnce(new RepairRequestError(0, 'Connection lost'))
    await click('Apply evaluated proposal')
    expect(document.querySelector('[role=status]').textContent).toContain('Publication status is unknown')
    expect(button('Evaluate proposal').disabled).toBe(true)
    expect(button('Check publication status').hidden).toBe(false)
    h.endpoints.poll.mockResolvedValue({ job_id: 'job-1', status: 'committed', revision: 5, stale: false, source_busy: false })
    await click('Check publication status')
    expect(h.endpoints.commit).toHaveBeenCalledTimes(1)
    expect(h.endpoints.apply).toHaveBeenCalledTimes(1)
    expect(h.endpoints.cancel).not.toHaveBeenCalled()
    expect(button('Check publication status').hidden).toBe(true)
  })

  it('restores original source bytes as metadata and requires an explicit rebase before evaluation', async () => {
    const h = setup({ draft: saved(), fields: [sourceField] }), original = h.store.getState().currentDesign
    await open(h); await select()
    const input = document.querySelector('input[type=file]'), file = new File(['PDB'], 'original.pdb')
    Object.defineProperty(input, 'files', { value: [file] }); input.dispatchEvent(new Event('change')); await flush()
    expect(h.endpoints.inspectSource.mock.calls[0][0]).toMatchObject({ operation: 'restore_published', feature_id: 'import',
      parameter: 'source', source, expected_draft_id: 'draft', expected_generation: 0, expected_revision: 4 })
    expect(h.endpoints.uploadSource.mock.calls[0][1]).toBe(file)
    expect(h.store.getState().currentDesign).toBe(original)
    expect(h.endpoints.mutate).not.toHaveBeenCalled(); expect(h.endpoints.apply).not.toHaveBeenCalled()
    expect(document.querySelector('[role=status]').textContent).toContain('explicit rebase required')
    h.endpoints.evaluate.mockRejectedValueOnce(new RepairRequestError(409, { code: 'draft_rebase_required', detail: 'Explicit rebase required' }))
    await click('Evaluate proposal')
    expect(button('Apply evaluated proposal').disabled).toBe(true)
    await click('Rebase proposal')
    expect(h.endpoints.mutate.mock.calls[0][0]).toMatchObject({ operation: 'rebase', expected_revision: 5 })
    expect(h.endpoints.mutate.mock.calls[0][0]).not.toHaveProperty('actions')
  })

  it('closes and cancels the original job when the document or same-ID session is reset', async () => {
    const h = setup({ draft: saved() }); await open(h); await evaluateReady(h)
    window.dispatchEvent(new Event('nadoc:document-reset'))
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(h.endpoints.cancel).toHaveBeenCalledWith('job-1', { context: expect.objectContaining({ docId: 'document', designId: 'part', revision: 4 }) })
    expect(h.panel.controller.getState().ready).toBe(false)
    await open(h)
    h.store.setState({ currentDesign: { ...h.store.getState().currentDesign, id: 'another' } })
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(h.endpoints.commit).not.toHaveBeenCalled()
  })

  it('ignores delayed input catalogs after navigation and disposes modal listeners', async () => {
    const h = setup(), pending = deferred(); await open(h)
    h.endpoints.inspectInputs.mockReturnValueOnce(pending.promise)
    const selecting = select()
    h.store.setState({ currentDesign: { ...h.store.getState().currentDesign, id: 'different' } })
    pending.resolve({ version: 1, assessment: 'inputs_only', design_id: 'part', revision: 4,
      feature_id: 'import', child_id: null, definition_supported: true, fields: [nameField] })
    await selecting
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(h.panel.controller.getState().inputs).toBeNull()
    h.panel.dispose()
    expect(h.host.children).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('closes an unloaded inspection immediately when its document context changes', async () => {
    const h = setup(), pending = deferred()
    h.endpoints.inspect.mockReturnValueOnce(pending.promise)
    h.panel.open()
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    expect(h.panel.controller.getState().loaded).toBe(false)
    h.store.setState({ currentDesign: { ...h.store.getState().currentDesign, id: 'different' } })
    expect(document.querySelector('[role=dialog]')).toBeNull()
    pending.resolve({ design_id: 'part', revision: 4, draft: saved() }); await flush()
    expect(h.endpoints.acknowledge).not.toHaveBeenCalled()
    expect(h.panel.controller.getState().draft).toBeNull()
  })

  it('explains protected and unsupported definitions without a generic JSON editing bypass', async () => {
    const h = setup({ draft: saved(), protectedLoadout: true }); await open(h); await select()
    expect(document.querySelector('[role=status]').textContent).toContain('read-only')
    expect(document.querySelector('[aria-label=Name]').disabled).toBe(true)
    expect(button('Evaluate proposal').disabled).toBe(true)
    expect(button('Discard proposal').disabled).toBe(true)
    h.endpoints.inspectInputs.mockResolvedValueOnce({ version: 1, assessment: 'inputs_only', design_id: 'part', revision: 4,
      feature_id: 'import', child_id: null, definition_supported: false, reason: { detail: 'Legacy construction needs migration' }, fields: [] })
    await select()
    expect(document.body.textContent).toContain('Legacy construction needs migration')
    expect(document.querySelector('textarea')).toBeNull()
    expect(h.endpoints.mutate).not.toHaveBeenCalled()
  })

  it('does not authorize numerical upgrades or evaluate a historical cursor', async () => {
    const h = setup({ draft: { ...saved(), actions: [{ action: 'upgrade_numerical_contract', feature_id: 'relax' }] } })
    await open(h)
    expect(document.body.textContent).toContain('separate atom and junction comparison review')
    expect(button('Evaluate proposal').disabled).toBe(true)
    expect(button('Apply evaluated proposal').disabled).toBe(true)
    h.store.setState({ currentDesign: { ...h.store.getState().currentDesign, feature_log_cursor: 0 } })
    await open(h)
    expect(document.querySelector('[role=status]').textContent).toContain('Return to the latest feature')
    expect(button('Check published recipe').disabled).toBe(true)
    expect(h.endpoints.evaluate).not.toHaveBeenCalled()
  })

  it('highlights the exact rendered row without altering navigation or other rows', () => {
    const list = document.createElement('div')
    list.innerHTML = '<div data-fl-row="1" class="fl-repair-focus"></div><div data-fl-row="2.0"></div>'
    focusPartRepairRow(list, { index: 1, subIndex: 0 })
    expect(list.querySelector('[data-fl-row="1"]').classList.contains('fl-repair-focus')).toBe(false)
    expect(list.querySelector('[data-fl-row="2.0"]').classList.contains('fl-repair-focus')).toBe(true)
  })
})
