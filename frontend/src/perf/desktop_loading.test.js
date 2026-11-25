import { expect, it } from 'vitest'
import { beginDesktopLoad, desktopLoadReady, desktopLoadRecords, endDesktopLoad, observeDesktopLoadFrame } from './desktop_loading.js'

it('does not confuse prepared data, hidden content, or a blank render with a visible result', () => {
  beginDesktopLoad('part')
  const frame = { rendered: true, covered: false, content: true }
  observeDesktopLoadFrame(frame)
  expect(desktopLoadRecords().current.status).toBeNull()
  desktopLoadReady()
  for (const invalid of [{ ...frame, covered: true }, { ...frame, rendered: false }, { ...frame, content: false }]) {
    observeDesktopLoadFrame(invalid)
    expect(desktopLoadRecords().current.status).toBeNull()
  }
  observeDesktopLoadFrame(frame)
  const result = desktopLoadRecords().current
  expect(result.status).toBe('Completed')
  expect(result.marks.map(m => m.name)).toEqual(['open-requested', 'display-prepared', 'first-uncovered-render'])
})

it('failed/superseded loads never become successful from a later unrelated frame', () => {
  beginDesktopLoad('old')
  desktopLoadReady()
  beginDesktopLoad('new')
  expect(desktopLoadRecords().history.at(-1).status).toBe('Superseded')
  endDesktopLoad('Failed')
  observeDesktopLoadFrame({ rendered: true, covered: false, content: true })
  expect(desktopLoadRecords().current.status).toBe('Failed')
})
