// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chooseAutostapleScope, mergeRegion, runAutostapleCommand, selectionRegion, strandRegion } from './region_autostaple.js'

const design = {
  helices: [{ id: 'h0', bp_start: 0, length_bp: 42 }, { id: 'h1', bp_start: 0, length_bp: 42 }],
  strands: [
    { id: 's1', domains: [{ helix_id: 'h0', start_bp: 20, end_bp: 10, direction: 'REVERSE' }, { helix_id: 'h1', start_bp: 10, end_bp: 30, direction: 'FORWARD' }] },
    { id: 's2', domains: [{ helix_id: 'h0', start_bp: 21, end_bp: 35, direction: 'FORWARD', overhang_id: 'ov1' }] },
  ],
  crossovers: [{ id: 'x1', half_a: { helix_id: 'h0', index: 7 }, half_b: { helix_id: 'h1', index: 7 } }],
  forced_ligations: [],
  cluster_transforms: [{ id: 'c1', helix_ids: ['h1'] }],
}
const state = items => ({ currentDesign: design, selection: { context: 'design', level: 'default', items, primary: items.at(-1) ?? null } })
afterEach(() => { document.body.innerHTML = '' })

describe('region from selection', () => {
  it('maps every positional selection kind to merged helix spans', () => {
    expect(selectionRegion(state([{ kind: 'strand', id: 's1' }]))).toEqual([
      { helix_id: 'h0', lo_bp: 10, hi_bp: 20 }, { helix_id: 'h1', lo_bp: 10, hi_bp: 30 }])
    expect(selectionRegion(state([{ kind: 'domain', strandId: 's1', domainIndex: 0 }, { kind: 'base', key: 'h0:21:FORWARD' }])))
      .toEqual([{ helix_id: 'h0', lo_bp: 10, hi_bp: 21 }])  // adjacent spans merge
    expect(selectionRegion(state([{ kind: 'crossover', id: 'x1', subtype: 'crossover' }]))).toEqual([
      { helix_id: 'h0', lo_bp: 7, hi_bp: 7 }, { helix_id: 'h1', lo_bp: 7, hi_bp: 7 }])
    expect(selectionRegion(state([{ kind: 'cluster', id: 'c1' }]))).toEqual([{ helix_id: 'h1', lo_bp: 0, hi_bp: 41 }])
    expect(selectionRegion(state([{ kind: 'overhang', id: 'ov1' }]))).toEqual([{ helix_id: 'h0', lo_bp: 21, hi_bp: 35 }])
    expect(selectionRegion(state([]))).toEqual([])
  })
  it('drops synthetic and unknown helices', () => {
    expect(mergeRegion(design, [{ helix_id: '__lnk__c', lo_bp: 0, hi_bp: 3 }, { helix_id: 'gone', lo_bp: 0, hi_bp: 1 }])).toEqual([])
  })
  it('maps cadnano strand selections', () => {
    expect(strandRegion(design, ['s2', 'missing'])).toEqual([{ helix_id: 'h0', lo_bp: 21, hi_bp: 35 }])
  })
})

describe('autostaple command', () => {
  const deps = over => ({ design, autostaple: vi.fn(async () => ({ full_autostaple: { region: { restapled: 3, kept: 9 }, auto_crossover: { placed: 4 } } })),
    lastError: () => ({ message: 'boom' }), toast: vi.fn(), showProgress: vi.fn(), hideProgress: vi.fn(), ...over })

  it('runs the whole structure directly when nothing is selected', async () => {
    const d = deps({ choose: vi.fn() })
    await runAutostapleCommand(d)
    expect(d.choose).not.toHaveBeenCalled()
    expect(d.autostaple).toHaveBeenCalledWith({ scaffold_name: 'M13mp18' })
  })
  it.each([['region', { scaffold_name: 'M13mp18', region: [{ helix_id: 'h0', lo_bp: 0, hi_bp: 5 }] }, /restapled 3/],
           ['all', { scaffold_name: 'M13mp18' }, /4 crossovers/]])('sends the %s choice', async (choice, body, message) => {
    const d = deps({ region: [{ helix_id: 'h0', lo_bp: 0, hi_bp: 5 }], choose: vi.fn(async () => choice) })
    await runAutostapleCommand(d)
    expect(d.autostaple).toHaveBeenCalledWith(body)
    expect(d.toast.mock.calls.at(-1)[0]).toMatch(message)
    expect(d.hideProgress).toHaveBeenCalledOnce()
  })
  it('does nothing on cancel and reports a failure', async () => {
    const cancelled = deps({ region: [{ helix_id: 'h0', lo_bp: 0, hi_bp: 5 }], choose: async () => null })
    expect(await runAutostapleCommand(cancelled)).toBeNull()
    expect(cancelled.autostaple).not.toHaveBeenCalled()
    const failed = deps({ autostaple: async () => null })
    await runAutostapleCommand(failed)
    expect(failed.toast).toHaveBeenCalledWith('Full autostaple failed: boom', { severity: 'error' })
  })
})

it('offers Cancel, Entire structure and Selection only', async () => {
  const button = label => [...document.querySelectorAll('button')].find(node => node.textContent === label)
  const pending = chooseAutostapleScope([{ helix_id: 'h0', lo_bp: 0, hi_bp: 5 }, { helix_id: 'h1', lo_bp: 0, hi_bp: 5 }])
  expect(document.body.textContent).toMatch(/2 bp spans on 2 helices/)
  button('Entire structure').click()
  expect(await pending).toBe('all')
  const cancelled = chooseAutostapleScope([{ helix_id: 'h0', lo_bp: 0, hi_bp: 5 }])
  button('Cancel').click()
  expect(await cancelled).toBeNull()
})
