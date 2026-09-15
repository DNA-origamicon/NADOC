import { expect, it, vi } from 'vitest'
import { createBoxSizeFailureNotifier } from './md_box_size_failure.js'

it('reports inline warnings, deduplicates polls and clears recovered jobs', () => {
  const report = vi.fn(), alert=vi.spyOn(window,'alert')
  const notify = createBoxSizeFailureNotifier(report)
  const job = { job_id: 'cube', design_name: 'cube_pore', status: 'failed',
    error: 'Preparation failed: Final box-size check failed: Box X needs at least 12 nm. Increase this initial box dimension in wizard tab 2 and prepare again.' }
  notify([{ ...job, status: 'preparing' }])
  expect(report).toHaveBeenLastCalledWith([])
  notify([job]);notify([job])
  expect(report).toHaveBeenCalledTimes(2)
  expect(report.mock.calls[1][0][0]).toMatchObject({name:'cube_pore',message:expect.stringContaining('Box X needs at least 12 nm')})
  expect(report.mock.calls[1][0][0].message).not.toContain('tab 2')
  expect(report.mock.calls[1][0][0].message).toContain('Box and solvent')
  expect(alert).not.toHaveBeenCalled()
  notify([{ ...job, status:'preparing' }])
  expect(report).toHaveBeenLastCalledWith([])
  alert.mockRestore()
})
