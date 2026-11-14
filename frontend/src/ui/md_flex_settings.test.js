// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { defaultFlexRange, validateFlexRange, flexRangeQuery, initMdFlexSettings, showMappedFlexScale } from './md_flex_settings.js'
import { flexRangeKey } from './md_flex_range.js'

afterEach(() => document.body.replaceChildren())
it('identifies equivalent default selections and distinguishes explicit ranges', () => {
  expect(flexRangeKey(null)).toBe(flexRangeKey({ start: null, end: null, interval: 1 }))
  expect(flexRangeKey({ start: 1, end: 200, interval: 1 })).not.toBe(flexRangeKey(null))
})
it('defaults to the last 200 available frames and validates inclusive intervals', () => {
  expect(defaultFlexRange(1000)).toEqual({ start: 801, end: 1000, interval: 1 })
  expect(defaultFlexRange(12)).toEqual({ start: 1, end: 12, interval: 1 })
  expect(validateFlexRange({ start: '4', end: '13', interval: '3' }, 100)).toEqual({ start: 4, end: 13, interval: 3 })
  for (const range of [{ start: 0, end: 10, interval: 1 }, { start: 5, end: 4, interval: 1 },
    { start: 1, end: 101, interval: 1 }, { start: 1, end: 10, interval: 1.2 }]) {
    expect(() => validateFlexRange(range, 100)).toThrow()
  }
  expect(flexRangeQuery({ start: 4, end: 13, interval: 3 })).toBe('?start=4&end=13&interval=3')
  expect(flexRangeQuery(null)).toBe('')
})
it('Cancel discards drafts; Apply stores the job-specific selection and begins work', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  const button = document.createElement('button'), apply = vi.fn()
  let job = 'A'
  const settings = initMdFlexSettings({ button, getJobId: () => job, getCounts: async () => [1000], onApply: apply })
  await settings.open()
  expect(document.querySelector('[name=start]').value).toBe('801')
  document.querySelector('[name=start]').value = '500'
  document.querySelector('[data-cancel]').click()
  expect(apply).not.toHaveBeenCalled()
  expect(settings.range(job)).toBeNull()
  await settings.open()
  document.querySelector('[name=start]').value = '4'
  document.querySelector('[name=end]').value = '13'
  document.querySelector('[name=interval]').value = '3'
  document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledExactlyOnceWith({ start: 4, end: 13, interval: 3 })
  expect(document.querySelector('dialog')).toBeNull()
  await settings.open()
  expect(document.querySelector('[name=start]').value).toBe('4')
  job = 'B'
  await settings.open()
  expect(document.querySelector('[name=start]').value).toBe('801')
  settings.reset('A')
  expect(settings.range('A')).toBeNull()
  settings.dispose()
})
it('shows scale controls for a preliminary map without resetting edits on updates', () => {
  const scale = { show: vi.fn(), updateRange: vi.fn(), isVisible: vi.fn(() => false) }, viz = { recolorRmsf: vi.fn() }
  showMappedFlexScale({ min: .1, max: .5, preliminary: true }, scale, viz)
  expect(scale.show).toHaveBeenCalledTimes(1)
  scale.show.mock.calls[0][0].onRecolor(.2, .4, 'turbo')
  expect(viz.recolorRmsf).toHaveBeenCalledWith(.2, .4, 'turbo')
  scale.isVisible.mockReturnValue(true)
  showMappedFlexScale({ min: .1, max: .8 }, scale, viz)
  expect(scale.show).toHaveBeenCalledTimes(1)
  expect(scale.updateRange).toHaveBeenCalledWith(.1, .8)
})
