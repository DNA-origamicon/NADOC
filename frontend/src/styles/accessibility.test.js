import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const css = fs.readFileSync(path.join(root, 'src/styles/accessibility.css'), 'utf8')
const tokens = fs.readFileSync(path.join(root, 'src/styles/tokens.css'), 'utf8')
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8')

describe('low-vision and reflow contract', () => {
  it('uses readable type and control token floors', () => {
    expect(tokens).toContain('--text-xs:    13px')
    expect(tokens).toContain('--text-base:  15px')
    expect(tokens).toContain('--control-sm:   32px')
    expect(tokens).toContain('--control-xl:   44px')
  })

  it('loads the final accessibility cascade after legacy inline rules', () => {
    expect(index.indexOf('src/styles/accessibility.css')).toBeGreaterThan(
      index.indexOf('</style>'),
    )
  })

  it('provides zoom reflow, coarse-pointer targets, and visible focus', () => {
    expect(css).toContain('@media (max-width: 900px)')
    expect(css).toContain('position: absolute')
    expect(css).toContain('@media (pointer: coarse)')
    expect(css).toContain('outline: 3px solid var(--color-accent)')
    expect(css).toContain('grid-template-columns: repeat(2, minmax(0, 1fr))')
    // Reflow depends on the viewport clamp, not the preferred desktop width.
    const welcomeRules = css.match(/#welcome-box\s*\{([^}]+)\}/)[1]
    expect(welcomeRules).toMatch(/width:\s*min\(\d+px, calc\(100% - 24px\)\)/)
    expect(welcomeRules).toContain('max-width: calc(100% - 24px)')
  })
})
