import { afterEach, expect, it, vi } from 'vitest'
import { initVisualizationCards } from './visualization_cards.js'

afterEach(() => document.body.replaceChildren())
it('collapses cards independently, restores preferences, and preserves live controls', () => {
  document.body.innerHTML = ['representation-modes-section', 'coloring-options-section', 'right-view-actions'].map(id =>
    `<section id="${id}"><h2>${id}</h2><div><button>Action</button></div></section>`).join('')
  const action = document.querySelector('#right-view-actions div button'), click = vi.fn()
  action.onclick = click
  const saved = new Map([['coloring-options-section', true]])
  const dispose = initVisualizationCards({ document,
    getCollapsed: (_, id) => saved.get(id) ?? false,
    setCollapsed: (_, id, value) => saved.set(id, value) })
  const cards = [...document.querySelectorAll('.visualization-card')]
  const toggle = card => card.querySelector('h2 button')
  expect(cards.map(card => toggle(card).getAttribute('aria-expanded'))).toEqual(['true', 'false', 'true'])
  toggle(cards[0]).click()
  expect(cards.map(card => card.lastElementChild.hidden)).toEqual([true, true, false])
  expect(saved.get('representation-modes-section')).toBe(true)
  expect(document.getElementById(toggle(cards[0]).getAttribute('aria-controls'))).toBe(cards[0].lastElementChild)
  action.click(); expect(click).toHaveBeenCalledOnce()
  toggle(cards[0]).click(); expect(cards[0].lastElementChild.hidden).toBe(false)
  dispose(); toggle(cards[0]).click(); expect(cards[0].lastElementChild.hidden).toBe(false)
})
