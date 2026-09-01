import { describe, expect, it } from 'vitest'
import { activeProjectContext, collaborationClientId } from './workspace_hub.js'

describe('activeProjectContext', () => {
  it('uses the immutable project id and active loadout branch', () => {
    expect(activeProjectContext({ currentDesign: {
      id: 'voltron', active_loadout_id: 'analysis',
      loadouts: [{ id: 'main' }, { id: 'analysis' }],
    }})).toEqual({ projectId: 'voltron', loadoutId: 'analysis' })
  })

  it('falls back to main for a legacy design and handles no design', () => {
    expect(activeProjectContext({ currentDesign: { id: 'legacy' } })).toEqual({ projectId: 'legacy', loadoutId: 'main' })
    expect(activeProjectContext({ currentDesign: null })).toBeNull()
  })
})

describe('collaborationClientId', () => {
  it('uses randomUUID in a secure context and persists the result', () => {
    const values = new Map()
    const storage = {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    }
    const id = collaborationClientId(storage, { randomUUID: () => 'secure-id' })
    expect(id).toBe('secure-id')
    expect(collaborationClientId(storage, {})).toBe('secure-id')
  })

  it('falls back to getRandomValues on plain HTTP origins', () => {
    const values = new Map()
    const storage = {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    }
    const cryptoApi = {
      getRandomValues: bytes => {
        bytes.fill(10)
        return bytes
      },
    }
    expect(collaborationClientId(storage, cryptoApi)).toBe('0a'.repeat(16))
  })

  it('still returns an id when storage access is blocked', () => {
    const storage = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
    }
    expect(collaborationClientId(storage, { randomUUID: () => 'memory-id' })).toBe('memory-id')
  })
})
