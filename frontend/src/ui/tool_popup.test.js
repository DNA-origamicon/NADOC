import { it, expect, vi } from 'vitest'
import { createToolPopup } from './tool_popup.js'

it('keeps live controls outside the sidebar and routes close through tool cancellation', () => {
  document.body.innerHTML = '<aside hidden><div id="tool" style="display:none"><h2>Test</h2><button id="action">Run</button></div></aside>'
  const panel = document.getElementById('tool'), action = document.getElementById('action')
  const run = vi.fn(), cancel = vi.fn()
  action.addEventListener('click', run)
  const popup = createToolPopup({ panel, title: 'Test', onClose: cancel })
  popup.show()
  expect(popup.root.parentElement).toBe(document.body)
  expect(panel.closest('aside')).toBeNull()
  expect(document.getElementById('action')).toBe(action)
  action.click()
  expect(run).toHaveBeenCalledOnce()
  popup.root.querySelector('[aria-label="Close Test"]').click()
  expect(cancel).toHaveBeenCalledOnce()
  popup.hide()
  expect(panel.style.display).toBe('none')
  expect(popup.root.style.display).toBe('none')
  popup.dispose()
  expect(document.querySelector('.tool-popup')).toBeNull()
  document.body.innerHTML = ''
})
