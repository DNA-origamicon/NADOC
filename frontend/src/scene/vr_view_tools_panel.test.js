import { describe, expect, it } from 'vitest'
import { VIEW_TOOL_MESSAGE, viewToolMessageLines, drawViewToolMessage } from './vr_view_tools_panel.js'

describe('VR view tablet status area', () => {
  const context = { measureText: text => ({ width: Array.from(text).length * 9 }) }
  it('retains short status and uses word boundaries for normal messages', () => {
    expect(viewToolMessageLines(context, 'Ready')).toEqual(['Ready'])
    const message = 'This design is already straight; there is no deformation to toggle.'
    const lines = viewToolMessageLines(context, message)
    expect(lines.join(' ')).toBe(message)
    expect(lines.every(line => context.measureText(line).width <= VIEW_TOOL_MESSAGE.width)).toBe(true)
  })
  it('bounds long errors and unbroken identifiers with an explicit ellipsis', () => {
    for (const message of ['View unavailable: ' + 'Export failed with detailed context. '.repeat(30), 'W'.repeat(800), '🧬'.repeat(200)]) {
      const lines = viewToolMessageLines(context, message)
      expect(lines).toHaveLength(VIEW_TOOL_MESSAGE.lines)
      expect(lines.at(-1).endsWith('...')).toBe(true)
      expect(lines.every(line => context.measureText(line).width <= VIEW_TOOL_MESSAGE.width)).toBe(true)
      expect(lines.join('')).not.toContain('\uFFFD')
    }
  })
  it('draws within the reserved footer and leaves the lower frame clear', () => {
    const calls = []
    drawViewToolMessage({ ...context, fillText: (...args) => calls.push(args) }, 'A long export failure '.repeat(50))
    expect(calls.length).toBeGreaterThan(1)
    for (const [line, x, y] of calls) {
      expect(x).toBeGreaterThan(344) // Dock button ends here.
      expect(x + context.measureText(line).width).toBeLessThanOrEqual(744)
      expect(y).toBeGreaterThanOrEqual(620)
      expect(y + 6).toBeLessThan(744)
    }
    expect(viewToolMessageLines(context, ' \n ')).toEqual([])
  })
})
