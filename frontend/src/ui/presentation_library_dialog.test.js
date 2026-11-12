import { afterEach, expect, it, vi } from 'vitest'
import { initPresentationLibraryDialog } from './presentation_library_dialog.js'
let ui
function setup(library) {
  document.body.innerHTML = '<div id="root"></div>'
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
  const onOpen = vi.fn()
  ui = initPresentationLibraryDialog({ root: document.getElementById('root'), library, onOpen })
  return onOpen
}
afterEach(() => { ui?.dispose(); document.body.replaceChildren(); vi.restoreAllMocks() })
const entry = { id: 'a', name: '<Talk>', size: 1048576, created_at: '2026-11-11T00:00:00Z' }
it('offers the fixed library instead of a file picker and waits for the full download', async () => {
  let finish
  const library = { list: async () => ({ entries: [entry, { ...entry, id: 'clip', kind: 'keyframe', name: 'Background clip' }], notice: 'Server folder: compiled_presentations' }),
    open: vi.fn(() => new Promise(resolve => { finish = resolve })) }
  const onOpen = setup(library)
  await ui.open()
  expect(document.querySelector('input[type=file]')).toBeNull()
  expect(document.querySelector('.presentation-library-list').textContent).toContain('<Talk>')
  expect(document.querySelector('.presentation-library-list').textContent).not.toContain('Background clip')
  expect(document.querySelectorAll('.presentation-library-list button')).toHaveLength(1)
  const button = document.querySelector('.presentation-library-list button')
  expect(button.textContent).toBe('Download and open')
  button.click()
  expect(button.disabled).toBe(true)
  expect(onOpen).not.toHaveBeenCalled()
  finish({ data: { title: 'Talk' }, notice: 'Saved on this device' })
  await vi.waitFor(() => expect(onOpen).toHaveBeenCalled())
})
it('does not open a late download after closing the picker', async () => {
  let finish
  const onOpen = setup({ list: async () => ({ entries: [entry] }), open: () => new Promise(r => { finish = r }) })
  await ui.open(); document.querySelector('.presentation-library-list button').click()
  ui.close(); finish({ data: {}, notice: '' }); await Promise.resolve()
  expect(onOpen).not.toHaveBeenCalled()
})
