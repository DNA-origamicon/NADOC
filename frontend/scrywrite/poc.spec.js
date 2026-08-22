import fs from 'node:fs/promises'
import path from 'node:path'
import { test, expect, repositoryRoot } from './fixture.js'

test('Move/Rotate cancel, confirm, and undo produce a diagnostic trace', async ({ scrywrite }) => {
  const scriptPath = path.join(
    repositoryRoot,
    'native',
    'vr_viewer',
    'examples',
    'scrywrite_move_rotate.scry',
  )
  const trace = await scrywrite.run(await fs.readFile(scriptPath, 'utf8'))

  expect(trace.result).toBe('passed')
  expect(trace.assertions).toBeGreaterThanOrEqual(12)
  expect(trace.coverage.selection_kinds).toContain('cluster')
  expect(trace.coverage.states).toEqual(expect.arrayContaining([
    'PREVIEW ONLY',
    'CANCELLED',
    'COMMITTING',
    'COMMITTED',
    'UNDOING',
    'UNDONE',
  ]))
  expect(trace.events.at(-1).effective_translation).toEqual([0, 0, 0])
})
