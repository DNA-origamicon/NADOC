import { afterEach, expect, it, vi } from 'vitest'
import { openProcessLog } from './process_log.js'
import { recordRequestDiagnostic, processLogSnapshot, clearProcessLog, recordProcess, PROCESS_LOG_LIMIT } from '../perf/process_log.js'

afterEach(() => {
  document.querySelector('#process-log [data-close]')?.click()
  clearProcessLog()
  vi.useRealTimers()
})
it('shows history before opening, updates running requests, and reports HTTP failures safely', () => {
  vi.useFakeTimers()
  recordRequestDiagnostic({ phase: 'start', id: 1, method: 'GET', path: '/<img onerror=alert(1)>' })
  openProcessLog()
  expect(document.querySelector('tbody').textContent).toContain('Running')
  expect(document.querySelector('tbody img')).toBeNull()
  document.querySelector('[data-autoscroll]').click()
  recordRequestDiagnostic({ phase: 'complete', id: 1, method: 'GET', path: '/<img onerror=alert(1)>', status: 500, durationMs: 1250, networkMs: 1000, serverTiming: 'build;dur=900' })
  vi.advanceTimersByTime(500)
  expect(document.querySelector('tbody').textContent).toContain('Failed')
  expect(document.querySelector('tbody').textContent).toContain('1.25 s')
  expect(document.querySelector('tbody').textContent).toContain('build;dur=900')
  openProcessLog()
  expect(document.querySelectorAll('#process-log')).toHaveLength(1)
  document.querySelector('[data-close]').click()
  expect(vi.getTimerCount()).toBe(0)
})
it('bounds history while retaining running work and clears only completed entries', () => {
  recordProcess('pending', { label: 'pending' })
  for (let i = 0; i < PROCESS_LOG_LIMIT + 10; i++) recordProcess(`done:${i}`, { status: 'Completed', durationMs: i })
  const snapshot = processLogSnapshot()
  expect(snapshot.entries).toHaveLength(PROCESS_LOG_LIMIT)
  expect(snapshot.discarded).toBeGreaterThan(0)
  clearProcessLog()
  expect(processLogSnapshot().entries).toEqual([expect.objectContaining({ label: 'pending' })])
  recordProcess('pending', { status: 'Completed' })
})
it('filters processes and sorts by duration', () => {
  recordProcess('fast', { label: 'fast', status: 'Completed', durationMs: 5 })
  recordProcess('slow', { label: 'slow', status: 'Completed', durationMs: 500 })
  openProcessLog()
  const sort = document.querySelector('#process-log select')
  sort.value = 'slow'; sort.dispatchEvent(new Event('change'))
  expect(document.querySelector('tbody tr').textContent).toContain('slow')
  const input = document.querySelector('#process-log input')
  input.value = 'fast'; input.dispatchEvent(new Event('input'))
  expect(document.querySelector('tbody').textContent).toContain('fast')
  expect(document.querySelector('tbody').textContent).not.toContain('slow')
})

it('finishes cancelled job requests instead of leaving them running', () => {
  recordRequestDiagnostic({ phase: 'start', id: 99, method: 'GET', path: '/jobs' })
  recordRequestDiagnostic({ phase: 'aborted', id: 99, method: 'GET', path: '/jobs', durationMs: 42 })
  expect(processLogSnapshot().entries).toContainEqual(expect.objectContaining({ status: 'Cancelled', durationMs: 42 }))
})

it('holds rows and scroll position until refresh or autoscroll is enabled', () => {
  vi.useFakeTimers()
  recordProcess('original', { label: 'original', status: 'Completed', durationMs: 5 })
  openProcessLog()
  const toggle = document.querySelector('[data-autoscroll]')
  const scroller = document.querySelector('.process-log-table')
  const body = document.querySelector('#process-log tbody')
  expect(toggle.checked).toBe(false)
  const originalRow = body.firstChild
  scroller.scrollTop = 120
  recordProcess('new', { label: 'new entry', status: 'Completed', durationMs: 10 })
  vi.advanceTimersByTime(1500)
  expect(body.firstChild).toBe(originalRow)
  expect(body.textContent).not.toContain('new entry')
  expect(scroller.scrollTop).toBe(120)
  document.querySelector('[data-refresh]').click()
  expect(body.textContent).toContain('new entry')
  expect(scroller.scrollTop).toBe(120)
  toggle.click()
  expect(scroller.scrollTop).toBe(0)
  recordProcess('live', { label: 'live entry', status: 'Completed', durationMs: 20 })
  vi.advanceTimersByTime(500)
  expect(body.textContent).toContain('live entry')
  toggle.click()
  const frozenRow = body.firstChild
  vi.advanceTimersByTime(1000)
  expect(body.firstChild).toBe(frozenRow)
})

it('updates status and duration in place with autoscroll off', () => {
  vi.useFakeTimers()
  recordRequestDiagnostic({ phase: 'start', id: 777, method: 'GET', path: '/jobs/active' })
  openProcessLog()
  const body = document.querySelector('#process-log tbody')
  const row = body.firstChild
  const name = row.cells[1].textContent
  const scroller = document.querySelector('.process-log-table')
  scroller.scrollTop = 100
  recordRequestDiagnostic({ phase: 'complete', id: 777, method: 'GET', path: '/jobs/active', status: 200, durationMs: 42 })
  recordProcess('another', { label: 'new entry', status: 'Completed', durationMs: 10 })
  vi.advanceTimersByTime(500)
  expect(body.firstChild).toBe(row)
  expect(row.cells[1].textContent).toBe(name)
  expect(row.cells[2].textContent).toBe('Completed')
  expect(row.cells[3].textContent).toBe('42.0 ms')
  expect(body.textContent).not.toContain('new entry')
  expect(scroller.scrollTop).toBe(100)
})
