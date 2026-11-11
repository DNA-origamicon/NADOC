// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { createPresentationCheckpointButton } from './presentation_checkpoint_button.js'
import { createFeatureLogFilters } from './feature_log_filters.js'

it('saves only on click, prevents duplicates, and reports errors', async () => {
  let reject
  const save = vi.fn(() => new Promise((resolve, no) => { reject = no }))
  const { root } = createPresentationCheckpointButton({ save })
  const button = root.querySelector('button')
  expect(save).not.toHaveBeenCalled()
  button.click(); button.click()
  expect(save).toHaveBeenCalledTimes(1)
  expect(button.disabled).toBe(true)
  reject(new Error('Save failed'))
  await vi.waitFor(() => expect(root.textContent).toContain('Save failed'))
  expect(button.disabled).toBe(false)
})

it('hides presentation checkpoints by default and enables their filter', () => {
  localStorage.clear()
  const onChange = vi.fn()
  const filters = createFeatureLogFilters({ onChange })
  document.body.append(filters.root)
  expect(filters.values.annotations).toBe(false)
  const row = [...filters.root.querySelectorAll('label')].find(row => row.textContent.includes('Annotations'))
  const checkbox = row.querySelector('input')
  expect(checkbox.disabled).toBe(false)
  checkbox.click()
  expect(filters.values.annotations).toBe(true)
  expect(onChange).toHaveBeenCalledOnce()
  filters.dispose(); localStorage.clear()
})
