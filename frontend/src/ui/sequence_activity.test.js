import { it, expect } from 'vitest'
import { createSequenceActivity } from './sequence_activity.js'
import { createSequenceDraftGuard } from './sequence_draft_guard.js'
it('shows a nonblocking spinner until overlapping edits and checks all finish', () => {
  document.body.innerHTML = '<input id="sequence">'
  const activity = createSequenceActivity(), edit = activity.begin(), check = activity.begin()
  const node = document.querySelector('#overhang-sequence-activity')
  expect(node.style.display).toBe('flex')
  expect(node.style.pointerEvents).toBe('none')
  document.querySelector('input').focus()
  expect(document.activeElement.id).toBe('sequence')
  edit(); edit()
  expect(node.style.display).toBe('flex')
  check()
  expect(node.style.display).toBe('none')
})
it('preserves an in-progress draft through older responses and refreshes on blur', async () => {
  document.body.innerHTML = '<section><input data-overhang-sequence="o"></section>'
  const root = document.querySelector('section'), guard = createSequenceDraftGuard(root)
  guard('part', () => {})
  const input = root.firstChild
  input.value = 'new draft'; input.focus()
  guard('part', () => { root.textContent = 'old response' })
  guard('part', () => { root.textContent = 'latest response' })
  expect(input.isConnected).toBe(true)
  expect(input.value).toBe('new draft')
  input.blur(); await Promise.resolve()
  expect(root.textContent).toBe('latest response')
})

it('keeps the Set button alive when a pending response arrives while the user clicks it', async () => {
  document.body.innerHTML = '<section><input data-overhang-sequence="o"><button>Set</button></section><input id="outside">'
  const root = document.querySelector('section'), guard = createSequenceDraftGuard(root)
  guard('part', () => {})
  const input = root.querySelector('input'), button = root.querySelector('button')
  let saved = false
  button.onclick = () => { saved = true }
  input.focus()
  guard('part', () => { root.textContent = 'refreshed' })
  button.focus(); await Promise.resolve()
  expect(button.isConnected).toBe(true)
  button.click(); expect(saved).toBe(true)
  document.querySelector('#outside').focus(); await Promise.resolve()
  expect(root.textContent).toBe('refreshed')
})
