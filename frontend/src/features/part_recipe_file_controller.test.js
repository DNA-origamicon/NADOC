import { expect, it, vi } from 'vitest'
import { createRecipeFileRecoveryController } from './part_recipe_file_controller.js'

const SHA = 'a'.repeat(64), OUTPUT_SHA = 'b'.repeat(64)
const upgrade = () => ({ label: 'Preserve empty group owners (v2)', action: {
  action: 'upgrade_cluster_creation', feature_id: 'feature', child_id: null,
  expected_version: 1, expected_cluster_id: 'owner', expected_definition_sha256: 'c'.repeat(64),
} })
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
function setup() {
  const file = new File(['{}'], 'original.nadoc'), choice = upgrade()
  const recovery = { source_sha256: SHA, source_size_bytes: file.size, source_design_id: 'original',
    excluded_fields: ['metadata', 'physical_state', 'loadouts'], stripped_recovery_field_count: 2,
    old_state_verified: false, basis: 'saved_recipe_inputs' }
  const review = { status: 'review', recovery, upgrades: [choice], issues: [] }
  const text = '{"id":"new","exact_integer":9007199254740993,"float":1.0}'
  const ready = { status: 'ready', recovery: { ...recovery, recovered_design_id: 'new' }, issues: [],
    validation: { passed: true }, proof: { status: 'verified' },
    recovered_file: { json_text: text, size_bytes: text.length, sha256: OUTPUT_SHA } }
  const api = { inspect: vi.fn(async () => review), recover: vi.fn(async () => ready) }
  const download = vi.fn(), hashFile = vi.fn(async () => SHA), hashText = vi.fn(async () => OUTPUT_SHA)
  const controller = createRecipeFileRecoveryController({ api, download, hashFile, hashText })
  controller.chooseFile(file)
  return { controller, file, choice, recovery, review, ready, api, download, hashFile, hashText }
}
async function propose(h) {
  await h.controller.inspect()
  h.controller.selectUpgrade(h.controller.getState().review.upgrades[0], true)
  h.controller.acknowledgeExclusions(true)
}

it('requires explicit selection and exclusion review, then downloads unchanged server text only on user action', async () => {
  const h = setup(); await h.controller.inspect()
  expect(h.controller.getState().actions).toEqual([])
  await h.controller.evaluate(); expect(h.api.recover).not.toHaveBeenCalled()
  h.controller.selectUpgrade(h.controller.getState().review.upgrades[0], true)
  await h.controller.evaluate(); expect(h.api.recover).not.toHaveBeenCalled()
  h.controller.acknowledgeExclusions(true); await h.controller.evaluate()
  expect(h.api.recover).toHaveBeenCalledExactlyOnceWith(h.file, {
    version: 1, expected_source_sha256: SHA, actions: [h.choice.action],
  }, { signal: expect.any(AbortSignal) })
  expect(h.download).not.toHaveBeenCalled()
  h.controller.download()
  expect(h.download).toHaveBeenCalledExactlyOnceWith(h.ready.recovered_file.json_text, 'original-recovered.nadoc')
  expect(h.controller.getState().ready).toBe(true)
  h.controller.dispose()
})

it('binds the inspection to the exact selected file size and independently hashed bytes', async () => {
  const h = setup()
  h.api.inspect.mockResolvedValue({ ...h.review, recovery: { ...h.recovery, source_sha256: 'd'.repeat(64) } })
  await h.controller.inspect()
  expect(h.controller.getState().review).toBeNull()
  expect(h.controller.getState().error).toBeTruthy()
  expect(h.api.recover).not.toHaveBeenCalled()
  h.controller.dispose()
})

it.each(['cancel', 'dispose', 'chooseFile'])('ignores a late inspection after %s and aborts its request', async operation => {
  const h = setup(), pending = deferred()
  h.api.inspect.mockReturnValue(pending.promise)
  const inspecting = h.controller.inspect()
  // Let the bounded file hash finish before checking the actual request signal.
  await Promise.resolve(); await Promise.resolve()
  expect(h.api.inspect).toHaveBeenCalledTimes(1)
  h.controller[operation](...(operation === 'chooseFile' ? [new File(['x'], 'other.nadoc')] : []))
  expect(h.api.inspect.mock.calls[0][1].signal.aborted).toBe(true)
  pending.resolve(h.review); await inspecting
  expect(h.controller.getState().review).toBeNull()
  expect(h.download).not.toHaveBeenCalled()
  h.controller.dispose()
})

it('ignores a ready result after cancellation even when the transport wins the abort race', async () => {
  const h = setup(), pending = deferred(); await propose(h)
  h.api.recover.mockReturnValue(pending.promise)
  const running = h.controller.evaluate(); h.controller.cancel()
  pending.resolve(h.ready); await running; h.controller.download()
  expect(h.controller.getState().ready).toBe(false)
  expect(h.download).not.toHaveBeenCalled()
  h.controller.dispose()
})

it.each([
  ['source receipt', h => { h.ready.recovery.source_sha256 = 'd'.repeat(64) }],
  ['same document identity', h => { h.ready.recovery.recovered_design_id = 'original' }],
  ['size', h => { h.ready.recovered_file.size_bytes++ }],
  ['digest', h => { h.ready.recovered_file.sha256 = 'd'.repeat(64) }],
  ['validation', h => { h.ready.validation.passed = false }],
  ['proof', h => { h.ready.proof.status = 'failed' }],
  ['candidate object', h => { h.ready.candidate = { id: 'unreviewed' } }],
])('never offers download on mismatched %s', async (_name, change) => {
  const h = setup(); await propose(h); change(h)
  await h.controller.evaluate(); h.controller.download()
  expect(h.controller.getState().ready).toBe(false)
  expect(h.controller.getState().error).toBeTruthy()
  expect(h.download).not.toHaveBeenCalled()
  h.controller.dispose()
})

it('preserves structured failed evaluation diagnostics without a downloadable candidate', async () => {
  const h = setup(); await propose(h)
  h.api.recover.mockResolvedValue({ status: 'failed', issues: [{ code: 'missing_reference', feature_id: 'feature' }], recovery: h.recovery })
  await h.controller.evaluate(); h.controller.download()
  expect(h.controller.getState().issues).toEqual([{ code: 'missing_reference', feature_id: 'feature' }])
  expect(h.controller.getState().ready).toBe(false)
  expect(h.download).not.toHaveBeenCalled(); h.controller.dispose()
})

it('rejects uninspected descriptor copies and invalidates a ready result when choices change', async () => {
  const h = setup(); await propose(h)
  expect(() => h.controller.selectUpgrade(upgrade(), true)).toThrow()
  await h.controller.evaluate()
  h.controller.selectUpgrade(h.controller.getState().review.upgrades[0], false)
  expect(h.controller.getState().ready).toBe(false)
  h.controller.download(); expect(h.download).not.toHaveBeenCalled(); h.controller.dispose()
})

it('bounds selected actions to64 while retaining a larger inspected offer list', async () => {
  const h = setup()
  h.review.upgrades = Array.from({ length: 2000 }, (_, i) => ({ ...upgrade(), action: { ...upgrade().action, feature_id: `feature-${i}` } }))
  await h.controller.inspect()
  const offers = h.controller.getState().review.upgrades
  expect(offers).toHaveLength(2000)
  for (const offer of offers.slice(0, 64)) h.controller.selectUpgrade(offer, true)
  expect(() => h.controller.selectUpgrade(offers[64], true)).toThrow(/64/)
  expect(h.controller.getState().actions).toHaveLength(64); h.controller.dispose()
})

it('ignores late digest checks after choosing another file, without sending or downloading stale work', async () => {
  const h = setup(), inputHash = deferred()
  h.hashFile.mockReturnValueOnce(inputHash.promise)
  const inspecting = h.controller.inspect()
  h.controller.chooseFile(new File(['new'], 'other.nadoc'))
  inputHash.resolve(SHA); await inspecting
  expect(h.api.inspect).not.toHaveBeenCalled()
  h.controller.chooseFile(h.file); await propose(h)
  const outputHash = deferred(); h.hashText.mockReturnValueOnce(outputHash.promise)
  const evaluating = h.controller.evaluate(); await Promise.resolve(); await Promise.resolve()
  expect(h.hashText).toHaveBeenCalledTimes(1)
  h.controller.chooseFile(new File(['new'], 'other.nadoc'))
  outputHash.resolve(OUTPUT_SHA); await evaluating; h.controller.download()
  expect(h.controller.getState().review).toBeNull(); expect(h.controller.getState().ready).toBe(false)
  expect(h.download).not.toHaveBeenCalled(); h.controller.dispose()
})

it('keeps exact inspection actions private and checks receipt exclusions and source byte count', async () => {
  const h = setup(); await propose(h)
  h.controller.getState().actions[0].expected_cluster_id = 'forged'
  h.choice.action.expected_definition_sha256 = 'd'.repeat(64)
  await h.controller.evaluate()
  expect(h.api.recover.mock.calls[0][1].actions[0]).toMatchObject({ expected_cluster_id: 'owner', expected_definition_sha256: 'c'.repeat(64) })
  h.ready.recovery = { ...h.ready.recovery, excluded_fields: [] }
  await h.controller.evaluate(); expect(h.controller.getState().ready).toBe(false)
  h.controller.chooseFile(h.file)
  h.api.inspect.mockResolvedValue({ ...h.review, recovery: { ...h.recovery, source_size_bytes: 3 } })
  await h.controller.inspect(); expect(h.controller.getState().review).toBeNull()
  h.controller.dispose()
})
