import { describe, expect, it } from 'vitest'
import { activeProjectContext } from './workspace_hub.js'

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
