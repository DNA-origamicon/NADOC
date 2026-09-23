import { it, expect, afterEach } from 'vitest'
import { visualizationProgress } from './visualization_progress.js'
afterEach(() => { document.body.innerHTML = '' })
it('relays current measured phases and ignores finished, hidden, or other-engine work', () => {
  document.body.innerHTML = '<div id="md-jobs-viz-body" style="display:none"><progress max="100" value="37"></progress><div hidden><progress value="0.8"></progress></div></div><div id="oxdna-jobs-viz-body"><div role="progressbar" aria-valuenow="82"></div></div>'
  expect(visualizationProgress(document, 'namd')).toEqual({ fraction: .37 })
  expect(visualizationProgress(document, 'oxdna')).toEqual({ fraction: .82 })
  document.querySelector('progress').value = 100
  expect(visualizationProgress(document, 'namd')).toBeNull()
  document.querySelector('progress').removeAttribute('value')
  expect(visualizationProgress(document, 'namd')).toEqual({ fraction: null })
})
