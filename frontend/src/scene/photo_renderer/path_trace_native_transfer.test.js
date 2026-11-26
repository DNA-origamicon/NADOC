import {it, expect, vi} from 'vitest'
import {sendNativeChunk} from './path_trace_native_transfer.js'

it('retries the exact same chunk after a lost connection/acknowledgement', async () => {
  const body = new Uint8Array([1,2,3]), options = {method:'POST',body,headers:{'X-NADOC-Upload-Offset':'4'}}
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue({ok:true})
  const checkResponse = vi.fn(), wait = vi.fn()
  await sendNativeChunk('/upload', options, {fetcher,checkResponse,wait})
  expect(fetcher.mock.calls).toEqual([['/upload',options],['/upload',options]])
  expect(wait).toHaveBeenCalledWith(250, undefined)
  expect(checkResponse).toHaveBeenCalledOnce()
})

it('waits for a previous interrupted append to finish rolling back', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({status:409,clone:()=>({text:async()=> 'An OptiX frame is already uploading or rendering'})}).mockResolvedValue({ok:true})
  await sendNativeChunk('/upload', {}, {fetcher,checkResponse:vi.fn(),wait:vi.fn()})
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('bounds retries and preserves the network error', async () => {
  const error = new TypeError('Failed to fetch'), fetcher = vi.fn().mockRejectedValue(error), wait = vi.fn()
  await expect(sendNativeChunk('/upload', {}, {fetcher,checkResponse:vi.fn(),wait})).rejects.toBe(error)
  expect(fetcher).toHaveBeenCalledTimes(4)
  expect(wait.mock.calls.map(c=>c[0])).toEqual([250,500,1000])
})

it('does not retry HTTP capacity/identity failures', async () => {
  const fetcher=vi.fn().mockResolvedValue({status:413}), wait=vi.fn()
  await expect(sendNativeChunk('/upload', {}, {fetcher,wait,checkResponse:async()=>{throw new Error('Capacity')}})).rejects.toThrow('Capacity')
  expect(fetcher).toHaveBeenCalledOnce();expect(wait).not.toHaveBeenCalled()
})

it('cancels retry backoff promptly without resending', async () => {
  const controller = new AbortController(), fetcher = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
  const result=sendNativeChunk('/upload', {signal:controller.signal}, {fetcher,checkResponse:vi.fn()})
  await Promise.resolve();controller.abort()
  await expect(result).rejects.toBe(controller.signal.reason)
  expect(fetcher).toHaveBeenCalledOnce()
})
