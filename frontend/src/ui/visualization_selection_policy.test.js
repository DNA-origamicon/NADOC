import { describe, expect, it, vi } from 'vitest'
import {
  applyMdVisualizationJobSwitch,
  mdVisualizationJobSwitchAction,
  selectionUpdatesVisualization,
} from './visualization_selection_policy.js'

describe('selectionUpdatesVisualization', () => {
  it('allows only the currently running selection to update visualization state', () => {
    expect(selectionUpdatesVisualization({ status: 'running' })).toBe(true)
    for (const status of ['queued', 'preparing', 'completed', 'failed', 'cancelled', 'stopped']) {
      expect(selectionUpdatesVisualization({ status })).toBe(false)
    }
  })

  it('keeps visualization state stable when the selection is cleared', () => {
    expect(selectionUpdatesVisualization(null)).toBe(false)
    expect(selectionUpdatesVisualization(undefined)).toBe(false)
  })
})

describe('applyMdVisualizationJobSwitch', () => {
  it.each(['off', 'display', 'flex', 'occupancy', 'none'])('runs only the %s handler', async (action) => {
    const handlers = Object.fromEntries(
      ['off', 'display', 'flex', 'occupancy', 'none'].map(key => [key, vi.fn()]),
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
    [{ occupancy: true }, 'occupancy'],
    [{ trajectory: true }, 'off'],
    [{}, 'none'],
  ])('maps the active view to the job-switch action', (state, action) => {
    expect(mdVisualizationJobSwitchAction(state)).toBe(action)
  })

  it('always turns trajectories off, even if malformed state reports another view', () => {
    expect(mdVisualizationJobSwitchAction({ display: true, trajectory: true })).toBe('off')
  })
})
