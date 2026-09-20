import { expect, it, vi } from 'vitest'
import { openViewerFile, viewerFilePath } from './viewer_file_open.js'

it('accepts native relative paths and refuses traversal, URLs, and unsupported data', () => {
  expect(viewerFilePath('parts/a.nadoc')).toBe('parts/a.nadoc')
  expect(viewerFilePath('parts\\a.nass')).toBe('parts/a.nass')
  for (const path of ['../a.nadoc', '/tmp/a.nadoc', 'C:\\a.nadoc', 'http://host/a.nadoc', 'a.txt', '', 'a/../b.nass']) expect(() => viewerFilePath(path)).toThrow()
})
it('uses the normal lifecycle for both parts and assemblies and surfaces failures', async () => {
  const fileOpen = { openPartFromServer: vi.fn(async () => true), openAssemblyFromServer: vi.fn(async () => true) }
  const getFileOpen = () => fileOpen
  await openViewerFile({ path: 'p.nadoc', getFileOpen })
  expect(fileOpen.openPartFromServer).toHaveBeenCalledWith('p.nadoc')
  await openViewerFile({ path: 'a.nass', getFileOpen })
  expect(fileOpen.openAssemblyFromServer).toHaveBeenCalledWith('a.nass')
  fileOpen.openAssemblyFromServer.mockResolvedValue(false)
  await expect(openViewerFile({ path: 'missing.nass', getFileOpen })).rejects.toThrow('File load failed')
})
