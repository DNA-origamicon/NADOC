// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
vi.mock('./folder_picker.js', () => ({ pickSystemFolder: vi.fn(async () => '/archive') }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { initJobArchive } from './job_archive_action.js'
import { showToast } from './toast.js'

it('reports an interrupted task instead of polling idle forever after restart', async () => {
  const api = { archiveMdJob: vi.fn(async () => ({})), mdArchiveStatus: vi.fn(async () => ({ state: 'idle' })) }
  const controller = initJobArchive({ api, kind: 'md' })
  expect(await controller.archive({ job_id: 'interrupted' })).toBe(false)
  expect(api.mdArchiveStatus).toHaveBeenCalledTimes(1)
  expect(showToast).toHaveBeenCalledWith(expect.stringContaining('destination may be incomplete'), { severity: 'error' })
})
