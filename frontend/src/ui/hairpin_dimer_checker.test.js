// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  HAIRPIN_DIMER_ACTIVE_LS_KEY,
  HAIRPIN_DIMER_REPORT_KEY,
  initHairpinDimerChecker,
} from './hairpin_dimer_checker.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'
import { OA, OB, makeDesign, makeReport, makeWarningReport } from '../test-helpers/hairpin_dimer_fixture.js'

const flush = async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)) }

function setup({ design = makeDesign(), response = makeReport(), designKey = 'currentDesign', active = false } = {}) {
  mountIds({ 'menu-seq-hairpin-dimer': 'button' })
  localStorage.setItem(HAIRPIN_DIMER_ACTIVE_LS_KEY, active ? '1' : '0')
  const store = createMockStore({ [designKey]: design, [HAIRPIN_DIMER_REPORT_KEY]: null })
  let generated = null
  let onBroadcast = null
  const deps = {
    store,
    designKey,
    checkHairpinDimer: vi.fn(async body => (typeof response === 'function' ? response(body) : response)),
    onOverhangSequencesGenerated: vi.fn(fn => { generated = fn; return () => { generated = null } }),
    showToast: vi.fn(),
    showProgress: vi.fn(),
    hideProgress: vi.fn(),
    broadcast: { emit: vi.fn(), onMessage: vi.fn(fn => { onBroadcast = fn; return () => {} }) },
    recheckDelayMs: 0,
  }
  const checker = initHairpinDimerChecker(deps)
  const btn = document.getElementById('menu-seq-hairpin-dimer')
  return { store, deps, checker, btn, fireGenerated: ids => generated?.(ids), fireBroadcast: d => onBroadcast?.(d) }
}

const shown = store => store.getState()[HAIRPIN_DIMER_REPORT_KEY]

describe('initHairpinDimerChecker — toggle', () => {
  beforeEach(() => { document.body.innerHTML = ''; localStorage.clear() })
  afterEach(() => vi.useRealTimers())

  it('the menu toggle turns the checker on (full check, warnings shown) and off (hidden)', async () => {
    const { store, deps, btn } = setup()
    expect(btn.classList.contains('is-on')).toBe(false)
    btn.click()
    await flush()
    expect(btn.classList.contains('is-on')).toBe(true)
    expect(deps.checkHairpinDimer).toHaveBeenCalledWith({}, { quiet: false })
    expect(shown(store).checks).toHaveLength(3)
    const [msg, opts] = deps.showToast.mock.calls.at(-1)
    expect(opts.severity).toBe('warning')
    expect(msg).toContain('2 strands with hairpin or self-dimer Tm > 30 °C, 2 above 50 °C (red ⚠) '
      + '(10 mM Mg²⁺, 0 mM Na⁺, 200 nM oligo)')
    expect(msg).toContain('3D view, cadnano editor')
    expect(localStorage.getItem(HAIRPIN_DIMER_ACTIVE_LS_KEY)).toBe('1')
    expect(deps.broadcast.emit).toHaveBeenCalledWith('hairpin-dimer-toggle', { active: true })

    btn.click()
    await flush()
    expect(btn.classList.contains('is-on')).toBe(false)
    expect(shown(store)).toBeNull()
    expect(localStorage.getItem(HAIRPIN_DIMER_ACTIVE_LS_KEY)).toBe('0')
    expect(deps.checkHairpinDimer).toHaveBeenCalledTimes(1)
  })

  it('reports a clean design as info and a failed request as an error', async () => {
    const clean = { ...makeReport(), checks: [makeReport().checks[1]], summary: { checked: 1, flagged: 0, unsequenced: 0 } }
    const a = setup({ response: clean })
    await a.checker.setActive(true)
    expect(a.deps.showToast.mock.calls.at(-1)[1].severity).toBe('info')
    expect(a.deps.showToast.mock.calls.at(-1)[0]).toMatch(/no hairpin or self-dimer Tm > 30 °C in 1 sequence/)

    const b = setup({ response: null })
    await b.checker.setActive(true)
    expect(b.deps.showToast).toHaveBeenLastCalledWith('Hairpin/dimer check failed.', { severity: 'error' })
  })

  it('remembers the toggle across page loads and checks quietly once a design is present', async () => {
    const { store, deps, btn } = setup({ active: true })
    expect(btn.classList.contains('is-on')).toBe(true)
    await flush()
    expect(deps.checkHairpinDimer).toHaveBeenCalledWith({}, { quiet: true })
    expect(shown(store).checks).toHaveLength(3)
    expect(deps.showToast).not.toHaveBeenCalled()
  })

  it('while on, an edit re-checks only what became stale', async () => {
    const { store, deps, checker } = setup()
    await checker.setActive(true)
    deps.checkHairpinDimer.mockClear()
    const edited = makeDesign()
    edited.overhangs = edited.overhangs.map(o => (o.id === OB ? { ...o, sequence: 'T'.repeat(22) } : o))
    store.setState({ currentDesign: edited })
    await flush()
    // OB changed; the linker binds OB so it is stale too. OA is still current.
    expect(deps.checkHairpinDimer).toHaveBeenCalledTimes(1)
    expect(deps.checkHairpinDimer.mock.calls[0][0]).toEqual({ overhang_ids: [OB], strand_ids: ['__lnk__c1__s'] })
  })

  it('a generation edit is checked once, not again by the live re-check', async () => {
    let release
    const gate = new Promise(r => { release = r })
    const { store, deps, fireGenerated } = setup({ active: true, response: async body => {
      if (body.overhang_ids) await gate
      return body.overhang_ids ? { ...makeReport({ scope: 'partial' }), checks: [] } : makeReport()
    } })
    await flush()
    deps.checkHairpinDimer.mockClear()
    const edited = makeDesign()
    edited.overhangs = edited.overhangs.map(o => (o.id === OB ? { ...o, sequence: 'T'.repeat(22) } : o))
    store.setState({ currentDesign: edited })       // the generate response lands…
    fireGenerated([OB])                              // …then the hook asks for OB
    await flush()                                    // live re-check fires while OB is in flight
    expect(deps.checkHairpinDimer).toHaveBeenCalledTimes(1)
    release()
    await flush()
    // After it lands the re-check runs for whatever is still stale (the empty
    // response here leaves OB unchecked), so a second request is legitimate.
    expect(deps.checkHairpinDimer.mock.calls[0][0]).toEqual({ overhang_ids: [OB] })
  })

  it('while off, edits trigger nothing', async () => {
    const { store, deps } = setup()
    store.setState({ currentDesign: { ...makeDesign() } })
    await flush()
    expect(deps.checkHairpinDimer).not.toHaveBeenCalled()
  })

  it('follows the toggle from another tab without echoing it back', async () => {
    const { store, deps, btn, fireBroadcast } = setup({ designKey: 'design' })
    await fireBroadcast({ type: 'hairpin-dimer-toggle', active: true })
    await flush()
    expect(btn.classList.contains('is-on')).toBe(true)
    expect(shown(store)).not.toBeNull()
    expect(deps.broadcast.emit).not.toHaveBeenCalled()
    expect(deps.showToast).not.toHaveBeenCalled()
  })
})

describe('initHairpinDimerChecker — generation auto-check', () => {
  beforeEach(() => { document.body.innerHTML = ''; localStorage.clear() })

  const partial = idx => ({ ...makeReport({ scope: 'partial' }), checks: [makeReport().checks[idx]] })

  it('checks exactly the generated overhangs even when the toggle is off, and points to it', async () => {
    const { store, deps, fireGenerated } = setup({ response: partial(0) })
    fireGenerated([OA, OA])
    await flush()
    expect(deps.checkHairpinDimer).toHaveBeenCalledWith({ overhang_ids: [OA] }, { quiet: true })
    expect(shown(store)).toBeNull()                                  // off → nothing marked
    const [msg, opts] = deps.showToast.mock.calls.at(-1)
    expect(opts.severity).toBe('error')                              // 96.6 °C > 50 °C → red toast
    expect(msg).toMatch(/^⚠ Overhang OH-A \(22 nt\): hairpin Tm 96\.6 °C/)
    expect(msg).toContain('turn on Tools › Sequencing › Hairpin/Dimer Checker [0]')
  })

  it('an amber-tier (30–50 °C) generated overhang gets a warning toast, not an error', async () => {
    const amber = { ...makeWarningReport(), scope: 'partial', checks: [makeWarningReport().checks[0]] }
    const { deps, fireGenerated } = setup({ response: amber })
    fireGenerated([OA])
    await flush()
    const [msg, opts] = deps.showToast.mock.calls.at(-1)
    expect(opts.severity).toBe('warning')
    expect(msg).toMatch(/hairpin Tm 42\.5 °C/)
  })

  it('while on, marks the generated overhang with no hint; clean results stay silent', async () => {
    const on = setup({ response: partial(0), active: true })
    await flush()
    on.deps.showToast.mockClear()
    on.fireGenerated([OA])
    await flush()
    expect(on.deps.showToast.mock.calls.at(-1)[0]).not.toContain('turn on')
    expect(shown(on.store)).not.toBeNull()

    const clean = setup({ response: partial(1) })
    clean.fireGenerated([OB])
    await flush()
    expect(clean.deps.showToast).not.toHaveBeenCalled()
  })
})
