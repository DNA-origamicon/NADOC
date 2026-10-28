import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createOxdnaJob, copyOxdnaJob, appendOxdnaRun, appendOxdnaField, startOxdnaSurfaceDeposition, getMdRunDirStatus } from './client.js'
import { setRunDir } from '../ui/run_location_preferences.js'

beforeEach(() => {
  localStorage.clear()
  setRunDir('/dna', 'oxdna'); setRunDir('/atoms', 'namd')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200,
    headers: { get: () => null }, json: async () => ({ job_id: 'new-job' }) })))
})
afterEach(() => vi.unstubAllGlobals())
it.each([
  ['relax', () => createOxdnaJob({})],
  ['copy', () => copyOxdnaJob('parent')],
  ['production', () => appendOxdnaRun('parent', {})],
  ['field', () => appendOxdnaField('parent', {})],
  ['deposition', () => startOxdnaSurfaceDeposition('parent', {})],
])('uses the oxDNA location for new %s jobs', async (_, create) => {
  await create()
  const call = fetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
  expect(JSON.parse(call[1].body).run_dir).toBe('/dna')
})
it('keeps an explicit per-request destination', async () => {
  await createOxdnaJob({ run_dir: '/special' })
  expect(JSON.parse(fetch.mock.calls[0][1].body).run_dir).toBe('/special')
})
it('requests the appropriate engine’s default folder', async () => {
  await getMdRunDirStatus(null, 'oxdna')
  expect(fetch.mock.calls[0][0]).toContain('engine=oxdna')
  await getMdRunDirStatus(null, 'namd')
  expect(fetch.mock.calls[1][0]).toContain('engine=namd')
})
