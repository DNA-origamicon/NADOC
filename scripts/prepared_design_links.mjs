import { randomBytes, createHash } from 'node:crypto'
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { homedir } from 'node:os'

/** Keep private invitations outside every editor/viewer static-file root. */
export function designLinksFile(dist, home = homedir()) {
  const workspace = createHash('sha256').update(resolve(dist, '..')).digest('hex').slice(0, 16)
  return join(home, '.nadoc', `presentation-links-${workspace}.json`)
}

/** Host-local invitation credentials; never stores or publishes design content. */
export async function createDesignLinks(file) {
  let records = []
  if (file) {
    try { records = JSON.parse(await readFile(file, 'utf8')) }
    catch (error) { if (error.code !== 'ENOENT') throw error }
  }
  let links = new Map(records.map(link => [link.key, link])), writes = Promise.resolve()
  return {
    find: id => [...links.values()].find(link => link.id === id),
    ensure(key, reset = false) {
      const task = writes.then(async () => {
        if (typeof key !== 'string' || !/^(part|assembly):[^\x00-\x1f]{1,200}$/.test(key)) throw new Error('Open a design before creating its link.')
        if (links.has(key) && !reset) return links.get(key)
        const link = { key, id: randomBytes(16).toString('hex'), invite: randomBytes(32).toString('hex'), qrToken: randomBytes(32).toString('hex'), password: randomBytes(12).toString('base64url') }
        const next = new Map(links).set(key, link)
        if (file) {
          await mkdir(dirname(file), { recursive: true, mode: 0o700 })
          await writeFile(file + '.tmp', JSON.stringify([...next.values()]), { mode: 0o600 })
          await rename(file + '.tmp', file)
        }
        // Failed persistence must preserve both the previous invitation and access.
        links = next
        return link
      })
      writes = task.catch(() => {})
      return task
    },
    get: key => links.get(key),
  }
}
