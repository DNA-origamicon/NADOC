import { beforeEach, expect, it } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { wireSpreadsheetRowSelection } from './spreadsheet_row_selection.js'

let tbody, store, controller
const pick = (id, modifiers = {}, target = 'td') => tbody.querySelector(`[data-strand-id="${id}"] ${target}`).dispatchEvent(new MouseEvent('click', { bubbles: true, ...modifiers }))
const selected = () => store.getState().selection.items.map(ref => ref.id)
beforeEach(() => {
  document.body.innerHTML = '<table><tbody></tbody></table>'
  tbody = document.querySelector('tbody')
  tbody.innerHTML = ['d', 'b', 'a', 'c', 'e'].map(id => `<tr data-strand-id="${id}"><td>${id}<input><button>edit</button></td></tr>`).join('')
  store = createMockStore({ currentDesign: { id: 'design', strands: [] } })
  controller = createSelectionController({ store })
  wireSpreadsheetRowSelection({ tbody, store })
})
it('selects inclusive sorted ranges, contracts them and makes the clicked endpoint primary', () => {
  pick('b'); pick('e', { shiftKey: true })
  expect(selected()).toEqual(['b', 'a', 'c', 'e'])
  pick('a', { shiftKey: true })
  expect(selected()).toEqual(['b', 'a'])
  pick('d', { shiftKey: true })
  expect(selected()).toEqual(['b', 'd'])
  expect(store.getState().selection.primary.id).toBe('d')
})
it('toggles against current 3D selection and can add a range or replace everything', () => {
  controller.replace([{ kind: 'strand', id: 'e' }])
  pick('b', { ctrlKey: true }); pick('c', { ctrlKey: true, shiftKey: true })
  expect(selected()).toEqual(['e', 'b', 'a', 'c'])
  pick('a', { ctrlKey: true }); expect(selected()).toEqual(['e', 'b', 'c'])
  pick('e', { metaKey: true }); expect(selected()).toEqual(['b', 'c'])
  pick('d'); expect(selected()).toEqual(['d'])
})
it('uses current row order after sorting and ignores hidden rows', () => {
  pick('b')
  tbody.prepend(tbody.lastElementChild)
  tbody.querySelector('[data-strand-id="d"]').hidden = true
  pick('e', { shiftKey: true })
  expect(selected()).toEqual(['b', 'e'])
})
it('resets anchors across documents and treats missing anchors as single picks', () => {
  pick('b'); store.setState({ currentDesign: { id: 'other', strands: [] } })
  pick('e', { shiftKey: true }); expect(selected()).toEqual(['e'])
  tbody.querySelector('[data-strand-id="e"]').remove()
  pick('a', { shiftKey: true }); expect(selected()).toEqual(['a'])
})
it('leaves editors and assembly context untouched', () => {
  pick('b'); pick('e', { ctrlKey: true }, 'input'); pick('c', { shiftKey: true }, 'button')
  expect(selected()).toEqual(['b'])
  controller.reload('assembly'); pick('c')
  expect(selected()).toEqual([])
})
