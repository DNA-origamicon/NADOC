import {nativeJSONBlob, nativeJSONChunks, nativeJSONSize, NATIVE_UPLOAD_CHUNK} from './path_trace_native_upload.js'
import {sendNativeChunk} from './path_trace_native_transfer.js'

const labels = {webgl: 'WebGL', webgpu: 'WebGPU', optix: 'OptiX'}

/** Preserve the original cause while locating failures in the shared export pipeline. */
export function traceExportError(error, backend, stage) {
  if (error?.name === 'AbortError') return error
  const message = error?.message ?? String(error)
  const network = /failed to fetch|fetch failed|networkerror|load failed|dynamically imported module/i.test(message)
  const hint = network && stage === 'loading the renderer'
    ? ' Reload NADOC and retry; a renderer module could not be downloaded.'
    : network && stage === 'preparing EM data'
      ? ' Check the NADOC backend connection and that the trajectory EM results are still available.' : ''
  return new Error(`${labels[backend] ?? backend} export failed while ${stage}: ${message}${hint}`, {cause: error})
}

/** Check the complete encoded upload before opening a request. An early server
 * rejection during a large upload can otherwise surface as a connection reset. */
export async function requestOptix(path, data, signal, {fetcher = globalThis.fetch, maxBytes = Infinity, method = 'POST', requestId, onProgress} = {}) {
  signal?.throwIfAborted()
  const size = method === 'GET' ? 0 : nativeJSONSize(data ?? {}, maxBytes)
  const chunked = path.endsWith('/frame') && size > NATIVE_UPLOAD_CHUNK
  const body = method === 'GET' || chunked ? undefined : await nativeJSONBlob(data ?? {}, {signal, maxBytes})
  signal?.throwIfAborted()
  const stage = path === '/session' ? 'starting the native renderer' : 'sending the scene or receiving the rendered frame'
  let response
  try {
    const headers = data?.width ? Object.fromEntries(['width','height','samples'].map(key=>[`X-NADOC-Frame-${key}`,String(data[key])])) : {}
    if(headers && requestId)headers['X-NADOC-Render-Id']=requestId
    if (chunked) {
      let offset = 0
      for await (const chunk of nativeJSONChunks(data, {signal})) {
        signal?.throwIfAborted()
        await sendNativeChunk(`/api/render/optix${path.replace(/\/frame$/, '/upload')}`, {
          method: 'POST', body: chunk, signal,
          headers: {...headers, 'Content-Type': 'application/json', 'X-NADOC-Upload-Offset': String(offset), 'X-NADOC-Upload-Bytes': String(size)},
        }, {fetcher, checkResponse})
        offset += chunk.byteLength
        onProgress?.({stage:'upload',fraction:offset/size,label:`Encoded / uploaded ${(offset/1048576).toFixed(1)} / ${(size/1048576).toFixed(1)} MiB`})
      }
      signal?.throwIfAborted()
      headers['X-NADOC-Upload-Bytes'] = String(size)
    }
    response = await fetcher(`/api/render/optix${path}`, {method, body, signal, headers})
  } catch (error) {
    signal?.throwIfAborted()
    if (error?.name === 'AbortError') throw error
    if (error?.message?.startsWith('OptiX HTTP ')) throw error
    throw new Error(`OptiX connection failed while ${stage}. Check that the NADOC backend is running, then retry. ${error?.message ?? error}`, {cause: error})
  }
  await checkResponse(response, stage)
  return response
}

async function checkResponse(response, stage) {
  if (!response.ok) {
    let detail = await response.text()
    try { detail = JSON.parse(detail).detail ?? detail } catch { /* retain non-JSON proxy errors */ }
    throw new Error(`OptiX HTTP ${response.status} while ${stage}: ${String(detail).slice(0, 800)}`)
  }
}
