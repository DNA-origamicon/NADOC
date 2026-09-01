export const SPREADSHEET_SORT_KEYS = Object.freeze(['group', 'color', 'length'])
export const DEFAULT_SPREADSHEET_SORT_ORDER = Object.freeze(['group', 'color', 'length'])

const SORT_LABELS = Object.freeze({ group: 'Group', color: 'Color', length: 'Length' })

export function readSpreadsheetSortOrder(storageKey) {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    if (Array.isArray(saved)
        && saved.length === DEFAULT_SPREADSHEET_SORT_ORDER.length
        && saved.every(key => SPREADSHEET_SORT_KEYS.includes(key))) {
      return [...saved]
    }
  } catch (_) { /* use the shared default */ }
  return [...DEFAULT_SPREADSHEET_SORT_ORDER]
}

/** Build the same compact three-priority sort control in both spreadsheets. */
export function initSpreadsheetSort({ toolbar, before = null, storageKey, onChange }) {
  const order = readSpreadsheetSortOrder(storageKey)
  if (!toolbar) return { order, element: null }

  const wrap = document.createElement('div')
  wrap.className = 'sheet-sort-wrap'

  const label = document.createElement('span')
  label.className = 'sheet-sort-label'
  label.textContent = 'Sort:'
  wrap.appendChild(label)

  order.forEach((selectedKey, index) => {
    const select = document.createElement('select')
    select.className = 'sheet-sort-select'
    select.title = `Sort priority ${index + 1}`
    select.setAttribute('aria-label', `Spreadsheet sort priority ${index + 1}`)

    for (const key of SPREADSHEET_SORT_KEYS) {
      const option = document.createElement('option')
      option.value = key
      option.textContent = SORT_LABELS[key]
      select.appendChild(option)
    }
    select.value = selectedKey
    select.addEventListener('change', () => {
      order[index] = select.value
      localStorage.setItem(storageKey, JSON.stringify(order))
      onChange?.(order)
    })
    wrap.appendChild(select)
  })

  toolbar.insertBefore(wrap, before)
  return { order, element: wrap }
}

