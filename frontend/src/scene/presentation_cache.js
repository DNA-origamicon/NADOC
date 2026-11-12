/** Browser-owned device storage, scoped to the NADOC origin. Never the Downloads folder. */
export function createPresentationCache() {
  async function transaction(mode, action) {
    if (!globalThis.indexedDB) throw new Error('Browser storage is unavailable')
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('nadoc-compiled-presentations', 1)
      request.onupgradeneeded = () => {
        request.result.createObjectStore('entries', { keyPath: 'id' })
        request.result.createObjectStore('files')
      }
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve(request.result)
    })
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(['entries', 'files'], mode)
        let request
        try { request = action(tx.objectStore('entries'), tx.objectStore('files')) }
        catch (error) { tx.abort(); reject(error); return }
        tx.oncomplete = () => resolve(request?.result)
        tx.onerror = tx.onabort = () => reject(tx.error || new Error('Device storage failed'))
      })
    } finally { db.close() }
  }
  return {
    list: () => transaction('readonly', entries => entries.getAll()),
    get: id => transaction('readonly', (_, files) => files.get(id)),
    put: (entry, blob) => transaction('readwrite', (entries, files) => {
      entries.put(entry); return files.put(blob, entry.id)
    }),
  }
}
