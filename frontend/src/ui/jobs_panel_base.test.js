// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  bodyDisplay,
  arrowChar,
  shouldPoll,
  applyArrow,
  initJobsPanelBase,
} from './jobs_panel_base.js'

// ── Pure decisions ────────────────────────────────────────────────────────────

describe('bodyDisplay', () => {
  it('hides when collapsed, shows otherwise', () => {
    expect(bodyDisplay(true)).toBe('none')
    expect(bodyDisplay(false)).toBe('')
  })
})

describe('arrowChar', () => {
  it('is ▾ open / ▸ closed (the mrDNA/CanDo idiom)', () => {
    expect(arrowChar(true)).toBe('▾')
    expect(arrowChar(false)).toBe('▸')
  })
})

describe('shouldPoll', () => {
  it('polls only when open AND active', () => {
    expect(shouldPoll({ open: true, hasActive: true })).toBe(true)
    expect(shouldPoll({ open: true, hasActive: false })).toBe(false)
    expect(shouldPoll({ open: false, hasActive: true })).toBe(false)
    expect(shouldPoll({ open: false, hasActive: false })).toBe(false)
  })
})

describe('applyArrow', () => {
  it("'text' idiom sets ▾/▸ via textContent", () => {
    const el = document.createElement('span')
    applyArrow(el, true, 'text'); expect(el.textContent).toBe('▾')
    applyArrow(el, false, 'text'); expect(el.textContent).toBe('▸')
    applyArrow(el, true); expect(el.textContent).toBe('▾')   // default
  })
  it("'class' idiom toggles is-collapsed (LAMMPS)", () => {
    const el = document.createElement('span')
    applyArrow(el, false, 'class'); expect(el.classList.contains('is-collapsed')).toBe(true)
    applyArrow(el, true, 'class'); expect(el.classList.contains('is-collapsed')).toBe(false)
  })
  it("'rotate' idiom sets a CSS transform (oxDNA/md)", () => {
    const el = document.createElement('span')
    applyArrow(el, true, 'rotate'); expect(el.style.transform).toBe('rotate(90deg)')
    applyArrow(el, false, 'rotate'); expect(el.style.transform).toBe('')
  })
  it('is a no-op on a null element', () => {
    expect(() => applyArrow(null, true)).not.toThrow()
  })
})

// ── Stateful factory — CONFORMANCE with the bespoke mrDNA/CanDo scaffold ───────
// The bespoke panels did, verbatim:
//   _applyCollapsed(c): body.display = c?'none':''; arrow.text = c?'▸':'▾';
//                       c ? _clearPoll() : _onOpen()
//   heading click: setSectionCollapsed(tab,section, isOpen); _applyCollapsed(isOpen)
//   advToggle click: advBody.display toggles; advArrow.text = shown?'▾':'▸'
//   _scheduleNextPoll(): _clearPoll(); if (open && hasActive) setTimeout(tick, POLL_MS)
// These tests pin that the base reproduces each effect.

function makeDom() {
  document.body.innerHTML = `
    <div id="p">
      <div id="heading">head</div>
      <div id="body">
        <button id="advToggle"></button>
        <span id="advArrow"></span>
        <div id="advBody" style="display:none"></div>
      </div>
      <span id="arrow"></span>
    </div>`
  const $ = (id) => document.getElementById(id)
  return {
    heading: $('heading'), body: $('body'), arrow: $('arrow'),
    advToggle: $('advToggle'), advArrow: $('advArrow'), advBody: $('advBody'),
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  try { localStorage.clear() } catch { /* jsdom */ }
})
afterEach(() => { vi.useRealTimers() })

describe('initJobsPanelBase — collapse', () => {
  it('applyCollapsed(true) hides body + sets ▸, fires onClose not onOpen', () => {
    const els = makeDom()
    const opened = vi.fn(); const closed = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, onOpen: opened, onClose: closed })
    base.applyCollapsed(true)
    expect(els.body.style.display).toBe('none')
    expect(els.arrow.textContent).toBe('▸')
    expect(closed).toHaveBeenCalledTimes(1)
    expect(opened).not.toHaveBeenCalled()
  })

  it('applyCollapsed(false) shows body + sets ▾, fires onOpen', () => {
    const els = makeDom()
    const opened = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, onOpen: opened })
    base.applyCollapsed(false)
    expect(els.body.style.display).toBe('')
    expect(els.arrow.textContent).toBe('▾')
    expect(opened).toHaveBeenCalledTimes(1)
    expect(base.isOpen()).toBe(true)
  })

  it('heading click collapses an open panel + persists the state', () => {
    const els = makeDom()
    els.body.style.display = ''       // start open
    const base = initJobsPanelBase({ section: 'p', els })
    els.heading.click()
    expect(els.body.style.display).toBe('none')
    expect(els.arrow.textContent).toBe('▸')
    expect(base.isOpen()).toBe(false)
    // a fresh base reads the persisted collapsed state on mount
    const base2 = initJobsPanelBase({ section: 'p', els: makeDom() })
    base2.initCollapsed(false)        // default open, but persisted=collapsed wins
    expect(document.getElementById('body').style.display).toBe('none')
  })

  it('heading click expands a collapsed panel', () => {
    const els = makeDom()
    els.body.style.display = 'none'   // start collapsed
    const opened = vi.fn()
    initJobsPanelBase({ section: 'p', els, onOpen: opened })
    els.heading.click()
    expect(els.body.style.display).toBe('')
    expect(opened).toHaveBeenCalledTimes(1)
  })

  it('initCollapsed defaults to collapsed with no persisted state', () => {
    const els = makeDom()
    const base = initJobsPanelBase({ section: 'p', els })
    base.initCollapsed(true)
    expect(els.body.style.display).toBe('none')
  })
})

// collapsible:false — the engine panels under the unified Simulate section. The
// *Simulate* header owns the one collapse; each engine header is a static label.
describe('initJobsPanelBase — collapsible:false (permanently open)', () => {
  it('the heading click does NOT collapse (no listener attached)', () => {
    const els = makeDom()
    els.body.style.display = ''
    const closed = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, collapsible: false, onClose: closed })
    els.heading.click()
    expect(els.body.style.display).toBe('')       // still open
    expect(base.isOpen()).toBe(true)
    expect(closed).not.toHaveBeenCalled()
  })

  it('initCollapsed forces the body OPEN (ignoring persisted state); onOpen fires deferred', async () => {
    // Persist a "collapsed" preference for section 'p' via a collapsible base's heading.
    const seedEls = makeDom(); seedEls.body.style.display = ''
    initJobsPanelBase({ section: 'p', els: seedEls }).initCollapsed(false)
    seedEls.heading.click()                          // collapse → persists collapsed=true
    // A collapsible:false base for the same section must ignore that and open.
    const els = makeDom()
    const opened = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, collapsible: false, onOpen: opened })
    base.initCollapsed(true)                         // arg ignored → forced open
    expect(els.body.style.display).toBe('')          // body opens synchronously
    expect(base.isOpen()).toBe(true)
    expect(opened).not.toHaveBeenCalled()            // onOpen is deferred (avoids init-time TDZ)
    await Promise.resolve()
    expect(opened).toHaveBeenCalledTimes(1)          // ...then fires on the microtask
  })

  it('still polls when a job is active (body is always open)', () => {
    const els = makeDom()
    const tick = vi.fn()
    const base = initJobsPanelBase({
      section: 'p', els, collapsible: false, pollMs: 1000, hasActive: () => true, tick,
    })
    base.initCollapsed(true)     // forced open
    base.schedulePoll()
    vi.advanceTimersByTime(1000)
    expect(tick).toHaveBeenCalledTimes(1)
  })

  it('the advanced drawer still toggles under collapsible:false', () => {
    const els = makeDom()
    initJobsPanelBase({ section: 'p', els, collapsible: false })
    expect(els.advBody.style.display).toBe('none')
    els.advToggle.click()
    expect(els.advBody.style.display).toBe('')
    els.advToggle.click()
    expect(els.advBody.style.display).toBe('none')
  })
})

describe('initJobsPanelBase — advanced drawer', () => {
  it('toggle shows the hidden advanced body + sets ▾, then hides + ▸', () => {
    const els = makeDom()
    initJobsPanelBase({ section: 'p', els })
    els.advToggle.click()
    expect(els.advBody.style.display).toBe('')
    expect(els.advArrow.textContent).toBe('▾')
    els.advToggle.click()
    expect(els.advBody.style.display).toBe('none')
    expect(els.advArrow.textContent).toBe('▸')
  })
})

describe('initJobsPanelBase — poll loop', () => {
  it('schedules tick after pollMs when open + active, then clears', () => {
    const els = makeDom(); els.body.style.display = ''  // open
    const tick = vi.fn()
    const base = initJobsPanelBase({
      section: 'p', els, pollMs: 1500, hasActive: () => true, tick,
    })
    base.schedulePoll()
    expect(tick).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1500)
    expect(tick).toHaveBeenCalledTimes(1)
    base.clearPoll()
    vi.advanceTimersByTime(5000)
    expect(tick).toHaveBeenCalledTimes(1)   // no re-fire after clear
  })

  it('does NOT schedule when collapsed even if active', () => {
    const els = makeDom(); els.body.style.display = 'none'  // collapsed
    const tick = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, hasActive: () => true, tick })
    base.schedulePoll()
    vi.advanceTimersByTime(5000)
    expect(tick).not.toHaveBeenCalled()
  })

  it('does NOT schedule when open but idle', () => {
    const els = makeDom(); els.body.style.display = ''
    const tick = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, hasActive: () => false, tick })
    base.schedulePoll()
    vi.advanceTimersByTime(5000)
    expect(tick).not.toHaveBeenCalled()
  })

  it('collapsing via applyCollapsed(true) clears a pending poll', () => {
    const els = makeDom(); els.body.style.display = ''
    const tick = vi.fn()
    const base = initJobsPanelBase({ section: 'p', els, hasActive: () => true, tick })
    base.schedulePoll()
    base.applyCollapsed(true)         // teardown path
    vi.advanceTimersByTime(5000)
    expect(tick).not.toHaveBeenCalled()
  })
})
