import { beforeEach, describe, expect, it, vi } from 'vitest'
import { spreadsheetColumns } from './spreadsheet_schema.js'
import { initSpreadsheetSort, readSpreadsheetSortOrder } from './spreadsheet_sort.js'

describe('shared spreadsheet structure', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    localStorage.clear()
  })

  it('uses one column schema, with Show as the only viewer-only column', () => {
    const editorKeys = spreadsheetColumns().map(column => column.key)
    const viewerKeys = spreadsheetColumns({ includeViewerOnly: true }).map(column => column.key)

    expect(viewerKeys.filter(key => key !== 'show')).toEqual(editorKeys)
    expect(viewerKeys).toContain('show')
  })

  it('builds and persists the shared compact sort controls', () => {
    const toolbar = document.createElement('div')
    const anchor = document.createElement('div')
    toolbar.appendChild(anchor)
    document.body.appendChild(toolbar)
    const onChange = vi.fn()

    const { order, element } = initSpreadsheetSort({
      toolbar,
      before: anchor,
      storageKey: 'test_sheet_sort',
      onChange,
    })

    expect(order).toEqual(['group', 'color', 'length'])
    expect(element.querySelectorAll('.sheet-sort-select')).toHaveLength(3)
    const first = element.querySelector('.sheet-sort-select')
    first.value = 'length'
    first.dispatchEvent(new Event('change', { bubbles: true }))
    expect(readSpreadsheetSortOrder('test_sheet_sort')).toEqual(['length', 'color', 'length'])
    expect(onChange).toHaveBeenCalled()
  })
})
