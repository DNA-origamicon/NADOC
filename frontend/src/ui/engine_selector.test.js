// @vitest-environment jsdom
/**
 * U4 oracle for the engine selector (unified-panel track).
 *
 * The selector collapses the five stacked simulation panels into ONE Simulate
 * section. This proves a CAPABILITY, not "it renders": selecting engine X shows
 * EXACTLY X's supported cards (from the U1 descriptor) and greys the rest —
 * present-with-a-why-reason, never absent. Three falsifiable anchors:
 *
 *   1. PURE STATE — `selectedEngineCards(e)` enabled subset === EXACTLY the U1
 *      `enabledCardKeys(e)`; greyed subset === EXACTLY the unsupported set, each
 *      carrying the descriptor's reason. `panelVisibility(e)` shows only e.
 *   2. DE-DUP — the selector reads the card facts from `engine_capabilities.js`
 *      (single source), so this test derives its ground truth from U1 too and
 *      any divergence between selector output and descriptor goes red.
 *   3. LIVE DOM — the factory shows exactly the selected engine's panel element
 *      and hides the other four, and the capability strip renders one chip per
 *      universe card (greyed chips carry the reason as a title tooltip).
 */
import { describe, it, expect, vi } from 'vitest'
import {
  ENGINE_KEYS, CARD_KEYS, ENGINE_LABELS,
  enabledCardKeys, supportsCard, cardReason,
} from './engine_capabilities.js'
import {
  panelVisibility, selectedEngineCards, isEngine, initEngineSelector,
} from './engine_selector.js'

describe('U4 pure selector state — driven by the U1 descriptor', () => {
  it('panelVisibility shows exactly the selected engine, hides the rest', () => {
    for (const sel of ENGINE_KEYS) {
      const vis = panelVisibility(sel)
      expect(Object.keys(vis).sort()).toEqual([...ENGINE_KEYS].sort())
      for (const k of ENGINE_KEYS) expect(vis[k]).toBe(k === sel)
    }
  })

  it('unknown selection hides every panel', () => {
    const vis = panelVisibility('nope')
    expect(Object.values(vis).every((v) => v === false)).toBe(true)
  })

  it('selectedEngineCards enabled subset === EXACTLY the U1 enabled cards', () => {
    for (const e of ENGINE_KEYS) {
      const cards = selectedEngineCards(e)
      // full universe present — no card ever absent
      expect(cards.map((c) => c.key)).toEqual([...CARD_KEYS])
      const enabled = cards.filter((c) => c.state === 'enabled').map((c) => c.key)
      expect(enabled).toEqual(enabledCardKeys(e))
    }
  })

  it('greyed cards === EXACTLY the unsupported set, each with the U1 reason', () => {
    for (const e of ENGINE_KEYS) {
      for (const card of selectedEngineCards(e)) {
        if (supportsCard(e, card.key)) {
          expect(card.state).toBe('enabled')
          expect(card.reason).toBeNull()
        } else {
          expect(card.state).toBe('greyed')
          expect(card.reason).toBe(cardReason(e, card.key))
          expect(typeof card.reason).toBe('string')
          expect(card.reason.length).toBeGreaterThan(0)
        }
      }
    }
  })

  it('unknown engine yields an empty census', () => {
    expect(selectedEngineCards('nope')).toEqual([])
    expect(isEngine('nope')).toBe(false)
    expect(ENGINE_KEYS.every(isEngine)).toBe(true)
  })
})

describe('U4 factory — wires the pure state to the DOM', () => {
  function harness() {
    const selectorMount = document.createElement('div')
    const stripMount = document.createElement('div')
    const panelEls = {}
    for (const k of ENGINE_KEYS) {
      const el = document.createElement('div')
      el.id = `${k}-jobs-panel-stub`
      document.body.appendChild(el)
      panelEls[k] = el
    }
    return { selectorMount, stripMount, panelEls }
  }

  it('renders one button per engine in U1 order', () => {
    const { selectorMount, panelEls } = harness()
    initEngineSelector({ selectorMount, panelEls })
    const btns = [...selectorMount.querySelectorAll('.engine-selector-btn')]
    expect(btns.map((b) => b.dataset.engine)).toEqual([...ENGINE_KEYS])
  })

  it('shows exactly the selected panel and hides the other four', () => {
    const { selectorMount, panelEls } = harness()
    const sel = initEngineSelector({ selectorMount, panelEls, initial: ENGINE_KEYS[0] })
    for (const target of ENGINE_KEYS) {
      sel.select(target)
      expect(sel.getSelected()).toBe(target)
      for (const k of ENGINE_KEYS) {
        const hidden = panelEls[k].style.display === 'none'
        expect(hidden).toBe(k !== target)
      }
      // active button marked
      const active = selectorMount.querySelector('.engine-selector-btn.is-active')
      expect(active.dataset.engine).toBe(target)
    }
  })

  it('a bad select() is a no-op (keeps the prior selection + visibility)', () => {
    const { selectorMount, panelEls } = harness()
    const sel = initEngineSelector({ selectorMount, panelEls, initial: 'namd' })
    sel.select('bogus')
    expect(sel.getSelected()).toBe('namd')
    expect(panelEls.namd.style.display).not.toBe('none')
  })

  it('strip renders one chip per universe card; greyed chips carry the reason tooltip', () => {
    const { selectorMount, stripMount, panelEls } = harness()
    const sel = initEngineSelector({ selectorMount, stripMount, panelEls })
    for (const e of ENGINE_KEYS) {
      sel.select(e)
      const chips = [...stripMount.querySelectorAll('.capability-chip')]
      expect(chips.map((c) => c.dataset.card)).toEqual([...CARD_KEYS])
      for (const chip of chips) {
        const key = chip.dataset.card
        if (supportsCard(e, key)) {
          expect(chip.classList.contains('is-enabled')).toBe(true)
        } else {
          expect(chip.classList.contains('is-greyed')).toBe(true)
          expect(chip.title).toBe(cardReason(e, key))
        }
      }
    }
  })

  it('fires onSelect once per selection with the engine key', () => {
    const { selectorMount, panelEls } = harness()
    const onSelect = vi.fn()
    const sel = initEngineSelector({ selectorMount, panelEls, initial: 'oxdna', onSelect })
    expect(onSelect).toHaveBeenCalledWith('oxdna') // initial select
    onSelect.mockClear()
    sel.select('cando')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('cando')
  })

  it('clicking a segmented-control button selects that engine', () => {
    const { selectorMount, panelEls } = harness()
    const sel = initEngineSelector({ selectorMount, panelEls, initial: ENGINE_KEYS[0] })
    const candoBtn = selectorMount.querySelector('.engine-selector-btn[data-engine="cando"]')
    candoBtn.click()
    expect(sel.getSelected()).toBe('cando')
    expect(panelEls.cando.style.display).not.toBe('none')
  })
})
