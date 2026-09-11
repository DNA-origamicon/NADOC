import { expect, it, vi } from 'vitest'
import { createBoxSizeFailureNotifier } from './md_box_size_failure.js'

it('opens a popup for a final cell failure once per job/error, including background jobs', () => {
  const alert = vi.fn()
  const notify = createBoxSizeFailureNotifier(alert)
  const job = { job_id: 'cube', design_name: 'cube_pore', status: 'failed',
    error: 'Preparation failed: Final box-size check failed: Box X needs at least 12 nm.' }
  notify([{ ...job, status: 'preparing' }])
  notify([{ ...job, error: 'Unrelated failure' }])
  expect(alert).not.toHaveBeenCalled()
  notify([job])
  notify([job])
  expect(alert).toHaveBeenCalledTimes(1)
  expect(alert.mock.calls[0][0]).toContain('cube_pore')
  expect(alert.mock.calls[0][0]).toContain('Box X needs at least 12 nm')
  expect(alert.mock.calls[0][0]).toContain('tab 2')
  notify([{ ...job, job_id: 'another-cube' }])
  expect(alert).toHaveBeenCalledTimes(2)
})
