// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { createVRFiles, saveBeforeVRFileSwitch, FILE_KEY_ROWS, fileTableDetail } from './vr_files.js'
import { createVRRouting } from './vr_routing.js'
it('uses standard QWERTY rows with a number row and spacebar', () => {
  expect(FILE_KEY_ROWS.map(row => row.join(' '))).toEqual([
    '1 2 3 4 5 6 7 8 9 0 delete', 'q w e r t y u i o p',
    'a s d f g h j k l', 'shift z x c v b n m dot dash underscore', 'space',
  ])
})
let bridge
afterEach(() => { bridge?.dispose(); document.body.innerHTML = '' })
const flush = async () => { for (let i=0;i<8;i++) await Promise.resolve() }
it('opens the filename keyboard, edits keys and cancels through versioned native events', async () => {
  const files = createVRFiles({ newPart: () => {
    document.body.innerHTML = '<div class="modal__overlay"><input id="new-design-name"><button>Cancel</button><button>Create</button></div>'
    document.querySelector('button').onclick = () => document.body.replaceChildren()
  } })
  let wire, sequence = 0
  bridge = createVRRouting({ files, request: async (_, o) => { wire = JSON.parse(o.body); return { ok: true } } })
  const click = async id => { await bridge.publish(); await bridge.activate({ id, sequence: ++sequence, version: wire.version }); await flush() }
  expect(files.snapshot().roots.find(r => r.id === 'file-assembly').enabled).toBe(false)
  await click('file-new')
  expect(bridge.snapshot().title).toBe('Filename keyboard')
  expect(bridge.snapshot().controls.filter(c => c.id.startsWith('file-key-'))).toHaveLength(42)
  await click('file-key-a'); await click('file-key-shift'); await click('file-key-b'); await click('file-key-1'); await click('file-key-delete')
  expect(document.querySelector('input').value).toBe('aB')
  await click(bridge.snapshot().controls.find(c => c.label === 'Cancel').id)
  expect(files.snapshot().title).toBe('')
})
it('does not replace a document when saving fails', async () => {
  const newPart = vi.fn(), onError = vi.fn()
  const files = createVRFiles({ newPart, beforeSwitch: async () => { throw Error('Save failed') }, onError })
  files.snapshot().roots.find(r => r.id === 'file-new').run(); await flush()
  expect(newPart).not.toHaveBeenCalled()
  expect(files.snapshot().controls.some(c => c.label === 'Save failed')).toBe(true)
})
it('requires successful save for both part and assembly switches', async () => {
  const deps = { store: { getState: () => ({ currentDesign: {} }) }, fileIo: { saveAs: vi.fn(async () => false), saveToWorkspace: vi.fn(async () => true) } }
  await expect(saveBeforeVRFileSwitch(deps)).rejects.toThrow('not saved')
  await expect(saveBeforeVRFileSwitch({ ...deps, workspacePath: 'part.nadoc' })).resolves.toBe(true)
  await expect(saveBeforeVRFileSwitch({ store: { getState: () => ({ assemblyActive: true }) }, api: { saveAssemblyToWorkspace: async () => null } })).rejects.toThrow('not saved')
})
it('reflects browser rows, save keyboard, and cancel without exposing destructive file actions', async () => {
  const files = createVRFiles({ saveAs: () => new Promise(() => {}) })
  files.snapshot().roots.find(r => r.id === 'file-save').run(); await flush()
  document.body.innerHTML = '<div data-vr-file-browser="save"><div data-vr-file-row="Folder">Folder</div><input data-vr-filename value="test"><button data-vr-file-action="Save">Save</button><button data-vr-file-action="Cancel">Cancel</button><button>Delete</button></div>'
  expect(files.snapshot().controls.map(r => r.label)).toEqual(['New Part','New Assembly','Open','Save As','Close Session','Folder','Filename: test','Workspace','Save','Cancel'])
  files.snapshot().controls.find(r => r.id === 'file-keyboard').run()
  expect(files.snapshot().title).toBe('Filename keyboard')
  files.snapshot().controls.find(r => r.id === 'file-key-2').run()
  expect(document.querySelector('input').value).toBe('test2')
})
it('opens a selected file in the current document, saves first, then refreshes VR', async () => {
  const order = []
  const files = createVRFiles({
    api: { listLibraryFiles: async () => [{ path: 'sample.nadoc', name: 'sample', type: 'part' }] },
    beforeSwitch: async () => { order.push('save'); return true },
    openPart: async path => { order.push(path); return true },
    refresh: async () => { order.push('refresh'); return { published: true } },
  })
  files.snapshot().roots.find(r => r.id === 'file-open').run(); await flush()
  const row = files.snapshot().controls.find(r => r.id.startsWith('file-entry-'))
  expect(row.label).toContain('sample.nadoc')
  row.run(); await flush()
  expect(order).toEqual(['save', 'sample.nadoc', 'refresh'])
  expect(files.snapshot().title).toBe('')
})
it('refreshes a newly created part and closes the session through the existing operation', async () => {
  let created
  const refresh = vi.fn(async () => ({ published: true })), closeSession = vi.fn(async () => {})
  const files = createVRFiles({ newPart: fn => { created = fn }, refresh, closeSession })
  files.snapshot().roots.find(r => r.id === 'file-new').run(); await flush()
  created(); await flush()
  expect(refresh).toHaveBeenCalledOnce()
  files.snapshot().roots.find(r => r.id === 'file-close').run(); await flush()
  expect(closeSession).toHaveBeenCalledOnce()
  expect(files.snapshot().title).toBe('')
})

it('publishes real table metadata without changing desktop row labels', () => {
  const row = document.createElement('div')
  Object.assign(row.dataset, { vrFileType:'Part', vrFileModified:'2026-11-23T10:00:00Z', vrFileSize:'2048' })
  expect(fileTableDetail(row)).toBe('Part|2026-11-23|2.0 KB')
  Object.assign(row.dataset, { vrFileType:'Folder', vrFileModified:'', vrFileSize:'' })
  expect(fileTableDetail(row)).toBe('Folder|--|--')
})
it('switches from the file table to New Part after cancelling the existing browser', async () => {
  const newPart = vi.fn(() => { document.body.innerHTML='<div class="modal__overlay"><input id="new-design-name"><button>Cancel</button></div>' })
  const files=createVRFiles({api:{listLibraryFiles:async()=>[]},newPart})
  files.snapshot().roots.find(r=>r.id==='file-open').run();await flush()
  expect(document.querySelector('[data-vr-file-browser]')).not.toBeNull()
  await files.snapshot().controls.find(r=>r.id==='file-new').run();await flush()
  expect(document.querySelector('[data-vr-file-browser]')).toBeNull()
  expect(newPart).toHaveBeenCalledOnce()
  expect(files.snapshot().title).toBe('Filename keyboard')
})
