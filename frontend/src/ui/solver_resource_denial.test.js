// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { showSolverResourceDenial } from './solver_resource_denial.js'
afterEach(() => document.body.replaceChildren())
it.each(['/snupi/jobs', '/mrdna/jobs', '/snupi/jobs/saved/start', '/mrdna/jobs/saved/start'])('blocks %s with a dismiss-only popup', path => {
  expect(showSolverResourceDenial(path, { code: 'memory_budget_exceeded', detail: 'RAM: 80 GiB required; 12 GiB available' }, 409)).toBe(true)
  expect(document.body.textContent).toContain('80 GiB required; 12 GiB available')
  expect(document.body.textContent).toContain('Job start denied')
  const ok = [...document.querySelectorAll('button')].find(b => b.textContent === 'OK')
  ok.click()
  expect(document.body.textContent).not.toContain('Job start denied')
})
it('does not turn unrelated errors into resource denials', () => {
  expect(showSolverResourceDenial('/snupi/jobs', { detail: 'Invalid input' }, 400)).toBe(false)
  expect(showSolverResourceDenial('/other', { code: 'memory_budget_exceeded' }, 409)).toBe(false)
})
