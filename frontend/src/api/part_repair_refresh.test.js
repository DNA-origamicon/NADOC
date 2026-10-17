import { expect, it, vi } from 'vitest'
import { createPartRepairEndpoints } from './part_repair_endpoints.js'

const context = { docId: 'original-doc', designId: 'part', loadoutId: 'main', revision: 4 }
const receipt = { job_id: 'job', status: 'committed', design_id: 'part', revision: 5 }
function setup() {
  const design = { design: { id: 'part', active_loadout_id: 'main' }, revision: 5, repair_draft: { generation: 0 } }
  const geometry = { nucleotides: [{ position: [0, 0, 0] }], helix_axes: [],
    straight_positions_by_helix: {}, straight_helix_axes: [] }
  const revision = { design_id: 'part', doc_id: 'original-doc', revision: 5, has_design: true }
  const status = { job_id: 'job', status: 'committed', revision: 5, stale: false, source_busy: false }
  const values = new Map([['/design', design], ['/design/geometry', geometry],
    ['/design/revision', revision], ['/design/features/evaluation/jobs/job', status]])
  const request = vi.fn(async (_method, path) => values.get(path)), apply = vi.fn(), acknowledge = vi.fn()
  return { api: createPartRepairEndpoints({ request, apply, acknowledge }), request, apply, acknowledge,
    values, design, geometry, revision, status }
}

it('collects a committed design and geometry privately and checks revision/session before returning one response', async () => {
  const h = setup(), abort = new AbortController()
  expect(await h.api.refreshCommitted(receipt, { context, signal: abort.signal })).toEqual({ ...h.design, ...h.geometry })
  expect(h.request.mock.calls.map(([method, path]) => [method, path])).toEqual([
    ['GET', '/design'], ['GET', '/design/geometry'], ['GET', '/design/revision'], ['GET', '/design/features/evaluation/jobs/job'],
  ])
  for (const [, , , options] of h.request.mock.calls) expect(options).toMatchObject({
    docId: 'original-doc', signal: abort.signal, protectedRetry: false, suppressBusy: true,
  })
  expect(h.apply).not.toHaveBeenCalled(); expect(h.acknowledge).not.toHaveBeenCalled()
})

it('matches the explicit server default identity without changing the null request context', async () => {
  const h = setup(), defaultContext = { ...context, docId: null }
  h.revision.doc_id = '__default__'
  expect(await h.api.refreshCommitted(receipt, { context: defaultContext })).toEqual({ ...h.design, ...h.geometry })
  expect(h.request).toHaveBeenCalledTimes(4)
  for (const [, , , options] of h.request.mock.calls) expect(options.docId).toBeNull()
  expect(defaultContext.docId).toBeNull()
  expect(h.apply).not.toHaveBeenCalled(); expect(h.acknowledge).not.toHaveBeenCalled()
})

it.each(['other-doc', undefined, null])('rejects an absent or different server document identity %s for the default document', async docId => {
  const h = setup()
  if (docId === undefined) delete h.revision.doc_id
  else h.revision.doc_id = docId
  await expect(h.api.refreshCommitted(receipt, { context: { ...context, docId: null } })).rejects.toMatchObject({ status: 409 })
  expect(h.request.mock.calls.map(([, path]) => path)).toEqual(['/design', '/design/geometry', '/design/revision'])
  expect(h.apply).not.toHaveBeenCalled(); expect(h.acknowledge).not.toHaveBeenCalled()
})

it.each([
  ['/design', { design: { id: 'other', active_loadout_id: 'main' }, revision: 5 }],
  ['/design/revision', { design_id: 'part', doc_id: 'original-doc', revision: 6, has_design: true }],
  ['/design/features/evaluation/jobs/job', { job_id: 'job', status: 'committed', revision: 5, stale: true, source_busy: false }],
  ['/design/features/evaluation/jobs/job', { job_id: 'job', status: 'committed', revision: 5, stale: false, source_busy: true }],
])('never exposes a private projection after an identity/revision/session guard fails at %s', async (path, value) => {
  const h = setup(); h.values.set(path, value)
  await expect(h.api.refreshCommitted(receipt, { context })).rejects.toThrow()
  expect(h.apply).not.toHaveBeenCalled(); expect(h.acknowledge).not.toHaveBeenCalled()
})

it('rejects an unrelated receipt before requesting design or geometry', async () => {
  const h = setup()
  await expect(h.api.refreshCommitted({ ...receipt, design_id: 'other' }, { context })).rejects.toThrow()
  expect(h.request).not.toHaveBeenCalled()
})
