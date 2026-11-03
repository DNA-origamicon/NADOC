import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { _request, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'
import { passiveReadScheduler } from './passive_read_scheduler.js'
const response = value => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => value })
beforeEach(() => {
  resetRevisionWatermark()
  store.setState({ currentDesign: null, assemblyActive: false, featureSeekPending: false })
})
afterEach(() => { passiveReadScheduler.reset(); vi.unstubAllGlobals() })

it('routes distinct passive consumers and foreground history through the same owner', async () => {
  let finish
  vi.stubGlobal('fetch', vi.fn(url => url.includes('dimensions')
    ? new Promise(resolve => { finish = () => resolve(response({ dimensions: [] })) })
    : Promise.resolve(response({ value: url }))))
  const first = _request('GET', '/design/dimensions?document_id=p', undefined, { suppressBusy: true })
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  const second = _request('GET', '/design/view-volumes?document_id=p', undefined, { suppressBusy: true })
  const foreground = _request('POST', '/design/features/deformation-preview', {}, { suppressBusy: true })
  await Promise.resolve(); expect(fetch).toHaveBeenCalledOnce()
  finish(); await Promise.all([first, second, foreground])
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/api/design/dimensions?document_id=p', '/api/design/features/deformation-preview', '/api/design/view-volumes?document_id=p',
  ])
})

it('retires queued display reads on document reset before dispatch', async () => {
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = () => resolve(response({})) })))
  const foreground = _request('POST', '/design/features/deformation-preview', {}, { suppressBusy: true })
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  const pending = _request('GET', '/design/view-volumes?document_id=p', undefined, { suppressBusy: true }).catch(e => e.name)
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(await pending).toBe('AbortError')
  finish(); await foreground
  expect(fetch).toHaveBeenCalledOnce()
})

it('does not dispatch a foreground mutation queued before a document reset', async () => {
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = () => resolve(response({})) })))
  const passive = _request('GET', '/jobs/active', undefined, { suppressBusy: true }).catch(e => e.name)
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  const foreground = _request('POST', '/design/example', {}, { suppressBusy: true })
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(await passive).toBe('AbortError')
  finish(); expect(await foreground).toBeNull()
  expect(fetch).toHaveBeenCalledOnce()
})
