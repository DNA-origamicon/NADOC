// @vitest-environment node
import { afterEach, expect, it } from 'vitest'
import { mkdtemp, mkdir, writeFile, access, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { gzipSync } from 'node:zlib'
import { cleanupProjectArtifacts } from '../../e2e/project_artifact_cleanup.js'

const roots = []
afterEach(async () => { for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true }) })
async function fixture(names) {
  const root = await mkdtemp(path.join(tmpdir(), 'nadoc-e2e-cleanup-'))
  roots.push(root)
  const project = path.join(root, '.nadoc-projects', 'test-project')
  await mkdir(path.join(project, 'snapshots'), { recursive: true })
  for (const [i, name] of names.entries()) {
    await writeFile(path.join(project, 'snapshots', `${i}.nadoc.gz`),
      gzipSync(JSON.stringify({ id: 'test-project', metadata: { name } })))
  }
  return { root, project }
}

it('removes only a requested project with entirely test-owned history', async () => {
  const { root, project } = await fixture(['__e2e__part', '__e2e__part'])
  expect(await cleanupProjectArtifacts(root, ['test-project', 'test-project'])).toEqual(['test-project'])
  await expect(access(project)).rejects.toThrow()
})

it('preserves mixed user/test history and rejects path traversal', async () => {
  const { root, project } = await fixture(['user-design', '__e2e__part'])
  expect(await cleanupProjectArtifacts(root, ['test-project', '../outside'])).toEqual([])
  await expect(access(project)).resolves.toBeUndefined()
})

it('preserves unrequested and corrupt stores', async () => {
  const { root, project } = await fixture(['__e2e__part'])
  expect(await cleanupProjectArtifacts(root, [])).toEqual([])
  await writeFile(path.join(project, 'snapshots', 'broken.nadoc.gz'), 'invalid')
  expect(await cleanupProjectArtifacts(root, ['test-project'])).toEqual([])
  await expect(access(project)).resolves.toBeUndefined()
})
