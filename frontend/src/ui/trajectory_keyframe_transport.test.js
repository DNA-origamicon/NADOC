import { expect, it, vi } from 'vitest'
import { attachTrajectoryTransport, createTrajectoryTimeline } from './trajectory_keyframe_transport.js'

it('keeps header and expanded buttons in sync and maps playback to the selected frame bounds', () => {
  const row = document.createElement('div'), header = document.createElement('div'), button = document.createElement('button')
  header.append(button); row.append(header)
  const bar = { el: document.createElement('div'), getRange: () => ({ start: 10, end: 20 }), setPlayhead: vi.fn() }
  const status = document.createElement('span'), progress = document.createElement('progress'), cancel = document.createElement('button')
  progress.max = 1
  const timeline = createTrajectoryTimeline({ keyframe: { id: 'k' }, bar, rangeInputs: document.createElement('div'), rangeLabel: document.createElement('span'),
    downloadStatus: status, downloadBar: progress, cancelPreparation: cancel, getFrameCount: () => 100, refreshLabel: vi.fn() })
  let notify
  const preview = { subscribe: fn => { notify = fn; return vi.fn() }, getState: () => ({}), toggle: vi.fn(), seek: vi.fn(), stop: vi.fn() }
  attachTrajectoryTransport({ row, keyframe: { id: 'k', trajectory_job_id: 'job' }, headerButton: button, timeline, preview })
  expect(header.nextElementSibling).toBe(timeline.element)
  expect(bar.el.nextElementSibling).toBe(timeline.transport)
  notify({ id: 'k', status: 'playing', time: 5, range: { holdStart: 3, end: 7 } })
  expect(bar.setPlayhead).toHaveBeenLastCalledWith(15)
  expect(button.getAttribute('aria-label')).toBe('Pause trajectory')
  expect(row.querySelector('[data-role="trajectory-play"]').getAttribute('aria-label')).toBe('Pause trajectory')
  row.querySelector('[data-role="trajectory-first"]').click()
  expect(preview.seek).toHaveBeenCalledWith('k', 0)
  row.querySelector('[data-role="trajectory-last"]').click()
  expect(preview.seek).toHaveBeenCalledWith('k', 1)
  row.querySelector('[data-role="trajectory-stop"]').click()
  expect(preview.stop).toHaveBeenCalledWith('k')
  notify({ id: 'k', status: 'loading', progress: { label: 'Downloading', done: 3, total: 4 } })
  expect(progress.value).toBe(.75); expect(cancel.hidden).toBe(false)
  expect(row.querySelector('[data-role="trajectory-first"]').disabled).toBe(true)
  notify({ id: 'other', status: 'playing' })
  expect(bar.setPlayhead).toHaveBeenLastCalledWith(null)
  expect(button.textContent).toBe('▶')
  expect(progress.hidden).toBe(true)
})
