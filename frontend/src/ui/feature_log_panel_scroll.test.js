import { describe, expect, it } from 'vitest'

import { isFeatureLogAtBottom, scrollFeatureLogToBottom } from './feature_log_panel.js'

function scrollBox({ scrollHeight = 1000, clientHeight = 200, scrollTop = 0 } = {}) {
  const el = document.createElement('div')
  Object.defineProperties(el, {
    scrollHeight: { configurable: true, value: scrollHeight },
    clientHeight: { configurable: true, value: clientHeight },
    scrollTop: { configurable: true, writable: true, value: scrollTop },
  })
  return el
}

describe('feature log bottom following', () => {
  it('recognizes the bottom with a small layout tolerance', () => {
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 800 }))).toBe(true)
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 794 }))).toBe(true)
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 780 }))).toBe(false)
  })

  it('scrolls to the newest entry without overshooting short lists', () => {
    const long = scrollBox({ scrollTop: 100 })
    scrollFeatureLogToBottom(long)
    expect(long.scrollTop).toBe(800)

    const short = scrollBox({ scrollHeight: 100, clientHeight: 200, scrollTop: 25 })
    scrollFeatureLogToBottom(short)
    expect(short.scrollTop).toBe(0)
  })
})
