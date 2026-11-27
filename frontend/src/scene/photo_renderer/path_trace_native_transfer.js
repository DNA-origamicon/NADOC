/** Retry only byte-verified, idempotent upload pieces. A render request is never
 * replayed: its result may have been lost after the GPU already started work. */
export async function sendNativeChunk(url, options, {fetcher, checkResponse, wait = pause}) {
  for (let attempt = 0; ; attempt++) {
    options.signal?.throwIfAborted()
    let response
    try {
      response = await fetcher(url, options)
    } catch (error) {
      options.signal?.throwIfAborted()
      if (!(error instanceof TypeError) || attempt >= 3) throw error
    }
    if (response) {
      // An earlier disconnected request may still be rolling back its piece.
      const busy = response.status === 409 && (await response.clone().text()).includes('already uploading or rendering')
      if (!busy || attempt >= 3) {
        await checkResponse(response, 'uploading the scene')
        return
      }
    }
    await wait(250 * 2 ** attempt, options.signal)
  }
}

function pause(ms, signal) {
  signal?.throwIfAborted()
  return new Promise((resolve, reject) => {
    const finish = () => { signal?.removeEventListener('abort', abort); resolve() }
    const timer = setTimeout(finish, ms)
    const abort = () => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(signal.reason) }
    signal?.addEventListener('abort', abort, {once: true})
  })
}
