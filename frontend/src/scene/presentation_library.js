import { docHeaders } from '../shared/doc_id.js'
import { createPresentationCache } from './presentation_cache.js'
import { readPresentationPackage } from './presentation_package.js'

const LIMIT = 512 * 1024 * 1024
const localNotice = 'Saved on this device. Keep the offline HTML file too if you need to reopen without the NADOC server.'
export function createPresentationLibrary({ cache = createPresentationCache(), request = (...args) => fetch(...args) } = {}) {
  async function check(response) {
    if (!response.ok) throw new Error(`Server request failed (${response.status})`)
    return response
  }
  async function keep(entry, blob) {
    try { await cache.put(entry, blob); return { deviceSaved: true, notice: localNotice } }
    catch { return { deviceSaved: false, notice: 'Could not save in browser storage. This tab can play it; download the offline HTML file to keep a local copy.' } }
  }
  async function serverList(signal) {
    const controller = new AbortController(), abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) controller.abort()
    const timeout = setTimeout(abort, 8000)
    try { return (await (await check(await request('/api/presentations', { headers: docHeaders(), signal: controller.signal }))).json()).items }
    finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort) }
  }
  return {
    async list(signal) {
      const [remote, local] = await Promise.allSettled([serverList(signal), cache.list()])
      const entries = new Map()
      for (const entry of local.status === 'fulfilled' ? local.value : []) entries.set(entry.id, { ...entry, deviceSaved: true })
      for (const entry of remote.status === 'fulfilled' ? remote.value : []) entries.set(entry.id, { ...entry, deviceSaved: !!entries.get(entry.id), serverSaved: true })
      return { entries: [...entries.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)),
        notice: remote.status === 'rejected' ? 'Server unavailable. Showing presentations saved on this device.' : 'Server folder: compiled_presentations',
      }
    },
    async save(blob, name, kind, signal) {
      let entry, serverSaved = false
      try {
        const response = await check(await request(`/api/presentations?${new URLSearchParams({ name: name.slice(0, 200), kind })}`, {
          method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'text/html' }, body: blob, signal,
        }))
        entry = await response.json(); serverSaved = true
      } catch (error) {
        if (signal?.aborted) throw error
        entry = { id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`, name, kind, size: blob.size, created_at: new Date().toISOString() }
      }
      const kept = await keep(entry, blob)
      return { entry, serverSaved, ...kept,
        notice: `${serverSaved ? 'Saved to presentation library.' : 'Server save failed; this presentation is not available on other machines.'} ${kept.notice}` }
    },
    async open(entry, { signal, onProgress = () => {} } = {}) {
      let blob
      try { blob = await cache.get(entry.id) } catch { /* Storage may be disabled; server remains usable. */ }
      const alreadySaved = !!blob && blob.size === entry.size
      if (!alreadySaved) {
        onProgress(0, entry.size)
        const response = await check(await request(`/api/presentations/${encodeURIComponent(entry.id)}/content`, { headers: docHeaders(), signal }))
        if (entry.size > LIMIT) throw new Error('Presentation exceeds 512 MiB')
        const chunks = []; let size = 0
        if (response.body?.getReader) {
          const reader = response.body.getReader()
          try {
            while (true) {
              signal?.throwIfAborted()
              const { done, value } = await reader.read()
              if (done) break
              size += value.byteLength
              if (size > LIMIT) throw new Error('Presentation exceeds 512 MiB')
              chunks.push(value); onProgress(size, entry.size)
            }
          } catch (error) { await reader.cancel().catch(() => {}); throw error }
          finally { reader.releaseLock() }
          blob = new Blob(chunks, { type: 'text/html' })
        } else blob = await response.blob()
        if (blob.size !== entry.size || blob.size > LIMIT) throw new Error('Incomplete presentation download. Please retry.')
      }
      signal?.throwIfAborted()
      const data = readPresentationPackage(await blob.text())
      signal?.throwIfAborted()
      const kept = alreadySaved ? { deviceSaved: true, notice: localNotice } : await keep(entry, blob)
      return { data, ...kept }
    },
  }
}
