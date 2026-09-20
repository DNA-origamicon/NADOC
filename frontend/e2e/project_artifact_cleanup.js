/** Remove only project stores whose complete snapshot history proves test ownership. */
import { readFile, readdir, rm } from 'node:fs/promises'
import { gunzipSync } from 'node:zlib'
import path from 'node:path'

const testName = name => typeof name === 'string' && /^(?:__e2e__|e2e__)/.test(name)
export async function cleanupProjectArtifacts(workspace, projectIds) {
  const removed = []
  for (const id of new Set(projectIds)) {
    if (typeof id !== 'string' || !/^[A-Za-z0-9_-]+$/.test(id)) continue
    const project = path.join(workspace, '.nadoc-projects', id)
    try {
      const snapshots = await readdir(path.join(project, 'snapshots'))
      if (!snapshots.length) continue
      let owned = true
      for (const name of snapshots) {
        if (!name.endsWith('.nadoc.gz')) { owned = false; break }
        const design = JSON.parse(gunzipSync(await readFile(path.join(project, 'snapshots', name))))
        if (design.id !== id || !testName(design.metadata?.name)) { owned = false; break }
      }
      if (!owned) continue
      await rm(project, { recursive: true, force: true })
      removed.push(id)
    } catch {
      // Unreadable, incomplete, or unfamiliar stores are not proven test artifacts.
    }
  }
  return removed
}
