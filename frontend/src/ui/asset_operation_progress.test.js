// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { showAssetOperationProgress } from './asset_operation_progress.js'
afterEach(() => { document.body.innerHTML = '' })
it('cancels before publication and keeps recovery visible during publication', () => {
  const cancel = vi.fn(), retry = vi.fn()
  let view = showAssetOperationProgress({ title: 'Fit nanoparticle', cancel })
  document.querySelector('button').click()
  expect(cancel).toHaveBeenCalledTimes(1)
  view = showAssetOperationProgress({ title: 'Fit nanoparticle', cancel })
  view.update('Refresh the saved result', { committing: true, refresh: retry })
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  expect(document.querySelector('[role="status"]').textContent).toBe('Refresh the saved result')
  const buttons = [...document.querySelectorAll('button')]
  expect(buttons.find(b => b.textContent === 'Cancel').disabled).toBe(true)
  buttons.find(b => b.textContent === 'Refresh result').click()
  expect(retry).toHaveBeenCalledTimes(1)
  view.close()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(cancel).toHaveBeenCalledTimes(1)
})
