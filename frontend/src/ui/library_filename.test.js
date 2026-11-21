// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { libraryRenameStem, libraryRenameFilename } from './library_filename.js'

describe('library rename filenames', () => {
  it.each([
    ['part', 'old.nadoc', 'rename_test', 'old', 'rename_test.nadoc'],
    ['part', 'old.nadoc', 'rename_test.nadoc', 'old', 'rename_test.nadoc'],
    ['part', 'old.NADOC', 'new.NADOC', 'old', 'new.nadoc'],
    ['part', 'old.nadoc', 'new.v2', 'old', 'new.v2.nadoc'],
    ['assembly', 'old.nass', 'new', 'old', 'new.nass'],
    ['assembly', 'old.nass', 'new.nass', 'old', 'new.nass'],
    ['folder', 'old.nadoc', 'new.nadoc', 'old.nadoc', 'new.nadoc'],
    ['part', 'old.nadoc', '  ', 'old', ''],
    ['part', 'old.nadoc', '.nadoc', 'old', ''],
  ])('%s: %s → %s', (type, path, input, stem, filename) => {
    const entry = { type, path }
    expect(libraryRenameStem(entry)).toBe(stem)
    expect(libraryRenameFilename(entry, input)).toBe(filename)
  })
})
