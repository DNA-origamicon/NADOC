import { describe, expect, it } from 'vitest'
import { isSimFolderPath, visibleWorkspaceEntries } from './sim_folders.js'

describe('simulation workspace folders', () => {
  it('recognizes engine roots and everything beneath them', () => {
    expect(isSimFolderPath('oxdna_jobs')).toBe(true)
    expect(isSimFolderPath('md_jobs/run-123/output.nadoc')).toBe(true)
    expect(isSimFolderPath('cando_jobs\\run-1')).toBe(true)
    expect(isSimFolderPath('future_engine_jobs/run-1')).toBe(true)
    expect(isSimFolderPath('Projects/md_jobs/design.nadoc')).toBe(false)
  })

  it('hides simulation entries by default and reveals them on request', () => {
    const entries = [
      { path: 'Designs/example.nadoc', type: 'part' },
      { path: 'mrdna_jobs', type: 'folder' },
      { path: 'mrdna_jobs/run-1', type: 'folder' },
    ]
    expect(visibleWorkspaceEntries(entries).map(e => e.path)).toEqual(['Designs/example.nadoc'])
    expect(visibleWorkspaceEntries(entries, true)).toBe(entries)
  })
})
