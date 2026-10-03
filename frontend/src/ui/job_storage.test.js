// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { gateStorageVisualization } from './job_storage.js'
import { selectionUpdatesVisualization } from './visualization_selection_policy.js'
import { buildJobRowModel } from './jobs_panel_model.js'
import { renderJobRow } from './jobs_panel_render.js'

describe('disconnected simulation storage', () => {
  const job = { job_id: 'offline', status: 'completed', archived: true,
    archive_path: '/mnt/e/simulations/offline', storage_available: false }

  it('disables visualization choices and explains the saved location', () => {
    const label = document.createElement('label')
    label.title = 'Original explanation'
    const radio = document.createElement('input')
    radio.type = 'radio'
    label.append(radio)
    expect(gateStorageVisualization(job, [radio])).toBe(true)
    expect(radio.disabled).toBe(true)
    expect(label.title).toContain(job.archive_path)
    expect(selectionUpdatesVisualization(job)).toBe(false)
    // Reconnection returns ownership of enablement to each engine’s normal gates.
    expect(gateStorageVisualization({ ...job, storage_available: true }, [radio])).toBe(false)
    expect(label.title).toBe('Original explanation')
    expect(selectionUpdatesVisualization({ ...job, storage_available: true })).toBe(true)
  })

  it.each([false, true])('renders an accessible SSD prohibition icon (compact=%s)', compact => {
    const m = buildJobRowModel(job, {
      compactColumns: () => compact, colors: { dim: '#888', warn: '#fa0' },
    }, { listIndex: 1 })
    const row = renderJobRow(m)
    const icon = row.querySelector('[data-storage-unavailable]')
    expect(icon).not.toBeNull()
    expect(icon.title).toContain('Connect or mount')
    expect(icon.getAttribute('aria-label')).toContain(job.archive_path)
    expect(icon.tabIndex).toBe(0)
    expect(icon.querySelector('svg rect')).not.toBeNull()
    expect(icon.querySelector('svg circle').getAttribute('stroke')).toBe('#f85149')
    const online = renderJobRow({ ...m, storageUnavailable: false })
    expect(online.querySelector('[data-storage-unavailable]')).toBeNull()
  })
})
