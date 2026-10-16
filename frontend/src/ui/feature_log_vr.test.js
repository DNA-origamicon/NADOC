// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { createFeatureLogVR, featureRowPosition } from './feature_log_vr.js'

describe('VR feature log uses desktop contracts', () => {
  it('maps initial, feature and expanded routing states exactly', () => {
    expect(featureRowPosition('0')).toEqual({ position: -2, subPosition: null })
    expect(featureRowPosition('4')).toEqual({ position: 3, subPosition: null })
    expect(featureRowPosition('4.2')).toEqual({ position: 3, subPosition: 2 })
    expect(() => featureRowPosition('x')).toThrow()
  })
  it('seeks without triggering delete and exposes only actual enabled actions', async () => {
    document.body.innerHTML = '<select id="target"><option>Part</option></select><div id="list"><div data-fl-row="0">F0 Initial</div><div data-fl-row="1.2">F1-3 Ligate<button title="Delete sub-step">X</button><button title="Edit feature" disabled>Edit</button></div></div>'
    const list = document.getElementById('list'), remove = vi.fn(), seek = vi.fn()
    list.querySelector('button').addEventListener('click', remove)
    const adapter = createFeatureLogVR({ list, target: document.getElementById('target'), prepare: vi.fn(), context: () => ({ cursor: 0, subCursor: 2, busy: false }), seek })
    const state = adapter.snapshot()
    expect(state.rows[1]).toMatchObject({ active: true, delete: true, edit: false, revert: false, label: 'F1-3 Ligate' })
    await adapter.activate('r:1')
    expect(seek).toHaveBeenCalledWith(0, 2);expect(remove).not.toHaveBeenCalled()
    await adapter.activate('a:1:delete');expect(remove).toHaveBeenCalledOnce()
    await adapter.activate('a:0:delete');expect(remove).toHaveBeenCalledOnce()
  })
  it('keeps the cluster header selected when its current sub-step is collapsed', () => {
    document.body.innerHTML = '<select></select><div id="list"><div data-fl-row="0">F0</div><div data-fl-row="1">F1 Routing</div></div>'
    const adapter = createFeatureLogVR({ list: document.getElementById('list'), target: document.querySelector('select'), prepare: vi.fn(), context: () => ({ cursor: 0, subCursor: 2 }) })
    expect(adapter.snapshot().rows[1].active).toBe(true)
  })
  it('preserves target changes and configuration selection', async () => {
    document.body.innerHTML = '<select><option value="assembly">Assembly</option><option value="part">Part</option></select><div id="list"><div data-fl-row="1">Config A</div></div>'
    const target = document.querySelector('select'), change = vi.fn(), seekConfig = vi.fn()
    target.addEventListener('change', change)
    const adapter = createFeatureLogVR({ list: document.getElementById('list'), target, prepare: vi.fn(), context: () => ({ configurations: true, cursor: -1, busy: false }), seekConfig })
    expect(adapter.snapshot().rows[0].active).toBe(true)
    await adapter.activate('t:1');expect(target.value).toBe('part');expect(change).toHaveBeenCalledOnce()
    await adapter.activate('r:0');expect(seekConfig).toHaveBeenCalledWith(0)
  })
})

it('marks native Edit dispatch while ordinary desktop clicks remain ordinary', async () => {
  document.body.innerHTML = '<select></select><div id="list"><div data-fl-row="1">Sweep<button title="Edit sweep path">Edit</button></div></div>'
  const button = document.querySelector('button'), clicks = []
  button.addEventListener('click', e => clicks.push(e.detail))
  const adapter = createFeatureLogVR({ list: document.getElementById('list'), target: document.querySelector('select'), prepare: () => {}, context: () => ({ cursor: -1 }) })
  await adapter.activate('a:0:edit')
  button.click()
  expect(clicks).toEqual([{ nativeVR: true }, 0])
})

it('propagates asynchronous native editor failures to the VR history coordinator', async () => {
  document.body.innerHTML = '<select></select><div id="list"><div data-fl-row="1">Sweep<button title="Edit sweep path">Edit</button></div></div>'
  document.querySelector('button').addEventListener('click', e => { e.detail.completion = Promise.reject(new Error('Sweep snapshot is unavailable')) })
  const adapter = createFeatureLogVR({ list: document.getElementById('list'), target: document.querySelector('select'), prepare: () => {}, context: () => ({ cursor: -1 }) })
  await expect(adapter.activate('a:0:edit')).rejects.toThrow('Sweep snapshot is unavailable')
})
