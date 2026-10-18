// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { initHistoryConversion } from './history_conversion.js'

const conversion = { status: 'converted', boundary: 3, absorbed: 3, rows: 4, editable: ['deformation'], frozen: 0, reason: '' }

function setup({ dry = { conversion, revision: 7 }, applied = { design: {} }, saved = { ok: true }, dest = { path: '/ws/joint (verified).nadoc', name: 'joint (verified)' }, confirm = true, original = '/ws/joint.nadoc' } = {}) {
  let workspacePath = original
  const calls = []
  const api = {
    convertHistory: vi.fn(async ({ apply }) => { calls.push(['convert', apply, workspacePath]); return apply ? applied : dry }),
    saveDesignAs: vi.fn(async (path, overwrite) => { calls.push(['save', path, overwrite]); return saved }),
  }
  const store = { getState: () => ({ currentDesign: { id: 'part', metadata: { name: 'joint' } }, assemblyActive: false, lastError: { message: 'boom' } }) }
  const deps = { api, store, showToast: vi.fn(), openFileBrowser: vi.fn(async () => dest), showConfirm: vi.fn(async () => confirm),
    getWorkspacePath: () => workspacePath, setWorkspacePath: vi.fn(path => { workspacePath = path }), setFileName: vi.fn(), button: null }
  return { ...deps, owner: initHistoryConversion(deps), calls, path: () => workspacePath }
}

describe('history conversion', () => {
  it('points autosave at the new file before applying, then saves without overwrite', async () => {
    const f = setup()
    expect(await f.owner.run()).toBe(true)
    expect(f.calls).toEqual([['convert', false, '/ws/joint.nadoc'], ['convert', true, '/ws/joint (verified).nadoc'],
      ['save', '/ws/joint (verified).nadoc', false]])
    expect(f.api.convertHistory).toHaveBeenLastCalledWith({ apply: true, expectedRevision: 7 })
    expect(f.openFileBrowser.mock.calls[0][0]).toMatchObject({ suggestedName: 'joint (verified)', noOverwrite: true })
    expect(f.setFileName).toHaveBeenCalledWith('joint (verified)')
  })

  it('refuses to reuse the original path and changes nothing', async () => {
    const f = setup({ dest: { path: '/ws/joint.nadoc', name: 'joint' } })
    expect(await f.owner.run()).toBe(false)
    expect(f.api.convertHistory).toHaveBeenCalledOnce()
    expect(f.path()).toBe('/ws/joint.nadoc')
  })

  it('restores the original path when Apply is refused', async () => {
    const f = setup({ applied: null })
    expect(await f.owner.run()).toBe(false)
    expect(f.path()).toBe('/ws/joint.nadoc')
    expect(f.api.saveDesignAs).not.toHaveBeenCalled()
  })

  it('stops after the dry run for native, refused or declined conversions', async () => {
    for (const f of [setup({ dry: { conversion: { ...conversion, status: 'already_native' }, revision: 1 } }),
      setup({ dry: { conversion: { ...conversion, status: 'refused', reason: 'no baseline' }, revision: 1 } }),
      setup({ confirm: false })]) {
      expect(await f.owner.run()).toBe(false)
      expect(f.api.convertHistory).toHaveBeenCalledOnce()
      expect(f.setWorkspacePath).not.toHaveBeenCalled()
    }
  })
})
