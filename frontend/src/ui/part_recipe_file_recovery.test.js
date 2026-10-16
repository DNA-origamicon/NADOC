import { afterEach, expect, it, vi } from 'vitest'
import { initRecipeFileRecovery, downloadRecoveredRecipe } from './part_recipe_file_recovery.js'

const mounted = [], flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve() }
const button = text => [...document.querySelectorAll('button')].find(node => node.textContent === text)
afterEach(() => { for (const view of mounted.splice(0)) view.dispose(); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('opens from File menu, explains exclusions, and requires explicit repair review before downloading a copy', async () => {
  document.body.innerHTML = '<button id="menu-file-recover-recipe">Recover recipe from file…</button>'
  const file = new File(['{}'], 'broken.nadoc'), sha = 'a'.repeat(64), text = '{"id":"new","large":9007199254740993}'
  const recovery = { source_sha256: sha, source_size_bytes: file.size, source_design_id: 'old',
    excluded_fields: ['metadata', 'loadouts', 'physical_state'], stripped_recovery_field_count: 3,
    old_state_verified: false, basis: 'saved_recipe_inputs' }
  const upgrade = { label: 'Preserve empty group owners (v2)', action: { action: 'upgrade_cluster_creation',
    feature_id: 'group', child_id: null, expected_version: 1, expected_cluster_id: 'owner', expected_definition_sha256: 'b'.repeat(64) } }
  const api = { inspect: vi.fn(async () => ({ status: 'review', recovery, upgrades: [upgrade], issues: [] })),
    recover: vi.fn(async () => ({ status: 'ready', recovery: { ...recovery, recovered_design_id: 'new' },
      validation: { passed: true }, proof: { status: 'verified' }, issues: [],
      recovered_file: { json_text: text, size_bytes: text.length, sha256: 'c'.repeat(64) } })) }
  const download = vi.fn(), view = initRecipeFileRecovery({ api, download,
    hashFile: async () => sha, hashText: async () => 'c'.repeat(64) }); mounted.push(view)
  document.getElementById('menu-file-recover-recipe').click()
  expect(document.querySelector('[role=dialog]')).toBeTruthy()
  expect(api.inspect).not.toHaveBeenCalled()
  const input = document.querySelector('input[type=file]')
  Object.defineProperty(input, 'files', { value: [file] }); input.dispatchEvent(new Event('change'))
  button('Inspect file').click(); await flush()
  expect(document.body.textContent).toContain('loadouts')
  expect(document.body.textContent).toContain('physical_state')
  expect(document.body.textContent).toMatch(/original.*unchanged/i)
  expect(document.body.textContent).toMatch(/not.*original geometry/i)
  expect(button('Evaluate recovery').disabled).toBe(true)
  const choice = document.querySelector('[aria-label="Preserve empty group owners (v2): group"]')
  expect(choice.checked).toBe(false)
  choice.checked = true; choice.dispatchEvent(new Event('change'))
  expect(button('Evaluate recovery').disabled).toBe(true)
  const acknowledgment = document.querySelector('[aria-label="I understand the excluded data is retained only in the original file"]')
  acknowledgment.checked = true; acknowledgment.dispatchEvent(new Event('change'))
  button('Evaluate recovery').click(); await flush()
  expect(api.recover).toHaveBeenCalledTimes(1)
  expect(download).not.toHaveBeenCalled()
  button('Download recovered copy').click()
  expect(download).toHaveBeenCalledExactlyOnceWith(text, 'broken-recovered.nadoc')
  view.close()
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(view.controller.getState().file).toBeNull()
})

it('does not create a modal or attach document work when the File menu entry is absent', () => {
  const api = { inspect: vi.fn(), recover: vi.fn() }, view = initRecipeFileRecovery({ api })
  expect(view).toBeNull()
  expect(api.inspect).not.toHaveBeenCalled(); expect(api.recover).not.toHaveBeenCalled()
})

it('downloads exact text bytes through a temporary URL and cleans up even if the browser click fails', async () => {
  const originalURL = URL, createObjectURL = vi.fn(() => 'blob:recovered'), revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', Object.assign(class extends originalURL {}, { createObjectURL, revokeObjectURL }))
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const text = '{"big":9007199254740993,"float":1.0,"unicode":"\\u03b1"}'
  downloadRecoveredRecipe(text, 'new-recovered.nadoc')
  const blob = createObjectURL.mock.calls[0][0]
  const bytes = await new Promise((resolve, reject) => { const reader = new FileReader()
    reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsArrayBuffer(blob) })
  expect(new TextDecoder().decode(bytes)).toBe(text); expect(blob.type).toBe('application/json')
  expect(click).toHaveBeenCalledTimes(1); expect(document.querySelector('a')).toBeNull()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(revokeObjectURL).toHaveBeenCalledTimes(1)
  // The second path checks cleanup on failure without dispatching a real download.
  vi.useFakeTimers(); click.mockImplementationOnce(() => { throw new Error('download blocked') })
  expect(() => downloadRecoveredRecipe(text, 'copy.nadoc')).toThrow('download blocked')
  expect(document.querySelector('a')).toBeNull(); await vi.runAllTimersAsync()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:recovered')
})

it('closes and cancels in-flight inspection, releases the original File and ignores a late response', async () => {
  document.body.innerHTML = '<button id="menu-file-recover-recipe">Recover recipe from file…</button>'
  let resolve
  const api = { inspect: vi.fn(() => new Promise(done => { resolve = done })), recover: vi.fn() }
  const view = initRecipeFileRecovery({ api, download: vi.fn(), hashFile: async () => 'a'.repeat(64) }); mounted.push(view)
  view.open(); view.controller.chooseFile(new File(['{}'], 'old.nadoc'))
  button('Inspect file').click(); await flush()
  const signal = api.inspect.mock.calls[0][1].signal
  view.close(); expect(signal.aborted).toBe(true)
  expect(view.controller.getState().file).toBeNull()
  resolve({ status: 'review' }); await flush(); view.open()
  expect(document.body.textContent).toContain('No file selected')
  expect(view.controller.getState().review).toBeNull()
})
