import { describe, expect, it, vi } from 'vitest'
import {
  applyMdVisualizationJobSwitch,
  mdVisualizationJobSwitchAction,
  selectionUpdatesVisualization,
} from './visualization_selection_policy.js'

describe('selectionUpdatesVisualization', () => {
  it('retargets visualization for every selected job, including historical parents', () => {
    for (const status of ['queued', 'preparing', 'running', 'completed', 'failed', 'cancelled', 'stopped']) {
      expect(selectionUpdatesVisualization({ status })).toBe(true)
    }
  })

  it('keeps visualization state stable when the selection is cleared', () => {
    expect(selectionUpdatesVisualization(null)).toBe(false)
    expect(selectionUpdatesVisualization(undefined)).toBe(false)
  })
})

describe('applyMdVisualizationJobSwitch', () => {
  it.each(['off', 'display', 'flex', 'photoproduct', 'occupancy', 'trajectory', 'none'])('runs only the %s handler', async (action) => {
    const handlers = Object.fromEntries(
      ['off', 'display', 'flex', 'photoproduct', 'occupancy', 'trajectory', 'none'].map(key => [key, vi.fn()]),
    )
    await applyMdVisualizationJobSwitch(action, handlers)
    expect(handlers[action]).toHaveBeenCalledOnce()
    for (const [key, handler] of Object.entries(handlers)) {
      if (key !== action) expect(handler).not.toHaveBeenCalled()
    }
  })
})

describe('mdVisualizationJobSwitchAction', () => {
  it.each([
    [{ display: true }, 'display'],
    [{ flex: true }, 'flex'],
    [{ photoproduct: true }, 'photoproduct'],
    [{ occupancy: true }, 'occupancy'],
    [{ trajectory: true }, 'trajectory'],
    [{}, 'none'],
  ])('maps the active view to the job-switch action', (state, action) => {
    expect(mdVisualizationJobSwitchAction(state)).toBe(action)
  })

  it('gives active trajectory playback priority if malformed state reports another view', () => {
    expect(mdVisualizationJobSwitchAction({ display: true, trajectory: true })).toBe('trajectory')
  })
})
