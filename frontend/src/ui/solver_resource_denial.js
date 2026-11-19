import { createModal } from './primitives/modal.js'

/** Shared by create and restart requests in both part and assembly hosts. */
export function showSolverResourceDenial(path, response, status) {
  if (!/^\/(snupi|mrdna)\/jobs(?:\/[^/]+\/start)?$/.test(path)) return false
  if (response?.code !== 'memory_budget_exceeded' && status !== 413) return false
  const body = document.createElement('p')
  body.style.whiteSpace = 'pre-wrap'
  body.textContent = typeof response?.detail === 'string' ? response.detail : 'Available resources could not be confirmed. The job was not started.'
  const close = document.createElement('button')
  close.textContent = 'OK'
  close.className = 'btn btn--primary'
  const modal = createModal({ title: 'Job start denied — insufficient resources', body, actions: [close] })
  close.addEventListener('click', () => modal.close())
  modal.open()
  return true
}
