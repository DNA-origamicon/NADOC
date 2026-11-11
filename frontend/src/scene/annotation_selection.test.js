import { expect, it, vi } from 'vitest'
import { createAnnotationSelection } from './annotation_selection.js'

it('links viewport, sidebar and popup selection, scrolls the card, and clears outside or on removal', () => {
  document.body.innerHTML = '<main><div data-annotation-id="a"></div></main><aside><div class="anno-card" data-annotation-id="a"><input></div><div data-annotation-id="a"><button></button></div></aside><footer></footer>'
  const container = document.querySelector('main'), pane = document.querySelector('aside')
  const card = pane.querySelector('.anno-card'); card.scrollIntoView = vi.fn()
  let onChange; const get = vi.fn(() => ({ id: 'a' }))
  const selection = createAnnotationSelection({ document, container, pane, controller: { get, subscribe(fn) { onChange = fn; return () => {} } } })
  const click = node => node.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
  click(container.firstChild)
  expect(selection.get()).toBe('a'); expect(card.classList.contains('is-selected')).toBe(true)
  expect(card.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
  click(document.querySelector('footer')); expect(selection.get()).toBeNull()
  pane.querySelector('input').focus(); expect(selection.get()).toBe('a')
  click(pane.querySelector('button')); expect(selection.get()).toBe('a')
  get.mockReturnValue(null); onChange(); expect(selection.get()).toBeNull()
  selection.dispose(); get.mockReturnValue({ id: 'a' }); click(container.firstChild)
  expect(selection.get()).toBeNull()
  document.body.replaceChildren()
})
