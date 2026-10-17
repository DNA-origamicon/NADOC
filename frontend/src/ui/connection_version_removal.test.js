import { describe, it, expect, vi } from 'vitest'
import { createConnectionVersionRemoval, nativeConnectionRemovalEnabled } from './connection_version_removal.js'

const version = { id: 'v', overhang_a_id: 'a', overhang_b_id: 'b', applied: true }
function setup(enabled = true) {
  const deps = { enabled: () => enabled, disconnect: vi.fn(async () => 'done'),
    patchVersion: vi.fn(), deleteVersion: vi.fn(), deleteConnection: vi.fn(), deleteBinding: vi.fn(),
    connections: () => [{ id: 'other', overhang_a_id: 'a', overhang_b_id: 'c' }, { ...version, id: 'link' }],
    bindings: () => [{ ...version, id: 'binding' }] }
  return { ...deps, api: createConnectionVersionRemoval(deps) }
}

describe('connection version removal', () => {
  it('keeps unqualified native rollout disabled', () => expect(nativeConnectionRemovalEnabled()).toBe(false))
  it.each(['unapply', 'remove'])('uses one atomic request for %s', async action => {
    const d = setup()
    expect(await d.api[action](version)).toBe('done')
    expect(d.disconnect).toHaveBeenCalledExactlyOnceWith('v', { deleteVersion: action === 'remove' })
    for (const fn of [d.patchVersion, d.deleteVersion, d.deleteConnection, d.deleteBinding]) expect(fn).not.toHaveBeenCalled()
  })
  it.each(['unapply', 'remove'])('does not retry failed native %s through legacy writes', async action => {
    const d = setup()
    d.disconnect.mockRejectedValue(new Error('source changed'))
    await expect(d.api[action](version)).rejects.toThrow('source changed')
    for (const fn of [d.patchVersion, d.deleteVersion, d.deleteConnection, d.deleteBinding]) expect(fn).not.toHaveBeenCalled()
  })
  it('keeps deleting an unapplied alternative metadata-only', async () => {
    const d = setup()
    await d.api.remove({ ...version, applied: false })
    expect(d.deleteVersion).toHaveBeenCalledExactlyOnceWith('v')
    expect(d.disconnect).not.toHaveBeenCalled()
  })
  it('preserves legacy ordering and exact pair selection while gated', async () => {
    const d = setup(false)
    await d.api.unapply(version)
    expect(d.deleteConnection).toHaveBeenCalledExactlyOnceWith('link')
    expect(d.deleteBinding).toHaveBeenCalledExactlyOnceWith('binding')
    expect(d.patchVersion).toHaveBeenCalledExactlyOnceWith('v', { applied: false })
    expect(d.deleteConnection.mock.invocationCallOrder[0]).toBeLessThan(d.deleteBinding.mock.invocationCallOrder[0])
    expect(d.deleteBinding.mock.invocationCallOrder[0]).toBeLessThan(d.patchVersion.mock.invocationCallOrder[0])
  })
})
