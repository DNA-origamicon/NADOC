/**
 * Structural invariants for index.html's top-level layout shell.
 *
 * #app is a flex COLUMN. The three layout children — #left-tab-strip,
 * #viewport-container, #right-panel — must live inside #main-area (a flex ROW).
 * If a stray </div> closes #main-area early, the HTML parser HOISTS them out to
 * become siblings of #main-area instead. They then stack vertically in the column
 * and the strip + panel consume the full height, collapsing #viewport-container
 * (and with it #canvas-area and #welcome-screen) to height 0. The app still boots,
 * throws no console error, and serves every module with a 200 — it is simply
 * invisible, which is what makes this worth a test.
 *
 * Happened for real: the "Exp. Photomode" tab landed with one more </div> than
 * <div> in its index.html block, closing #main-area ~230 lines early and taking
 * the welcome screen off-screen.
 *
 * These parse with the SAME hoisting behaviour the browser uses (jsdom), so they
 * assert what actually renders rather than counting tags.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const INDEX_HTML = resolve(HERE, '..', 'index.html')

let doc

beforeAll(() => {
  const html = readFileSync(INDEX_HTML, 'utf8')
  doc = new DOMParser().parseFromString(html, 'text/html')
})

const byId = (id) => doc.getElementById(id)

describe('index.html layout shell', () => {
  it('has the shell elements at all', () => {
    for (const id of ['app', 'main-area', 'left-tab-strip', 'viewport-container',
                      'right-panel', 'canvas-area', 'welcome-screen']) {
      expect(byId(id), `#${id} missing from index.html`).toBeTruthy()
    }
  })

  it.each(['left-tab-strip', 'viewport-container', 'right-panel'])(
    '#%s is a direct child of #main-area',
    (id) => {
      // The exact failure mode: an early </div> hoists these up to be SIBLINGS of
      // #main-area, inside the #app column, and the viewport collapses to 0 height.
      expect(byId(id).parentElement?.id).toBe('main-area')
    },
  )

  it('#main-area is a direct child of #app and is not empty', () => {
    expect(byId('main-area').parentElement?.id).toBe('app')
    expect(byId('main-area').children.length).toBeGreaterThan(0)
  })

  it('#welcome-screen sits inside #canvas-area inside #viewport-container', () => {
    expect(byId('welcome-screen').parentElement?.id).toBe('canvas-area')
    expect(byId('canvas-area').parentElement?.id).toBe('viewport-container')
  })

  it('every tab panel stays inside the left panel, not hoisted to the shell', () => {
    // A tab body that escapes its panel is the same bug wearing a different hat:
    // it renders as a full-width block in the column and pushes the viewport away.
    const panels = [...doc.querySelectorAll('.tab-content')]
    expect(panels.length).toBeGreaterThan(0)
    const stranded = panels
      .filter((p) => ['app', 'main-area'].includes(p.parentElement?.id))
      .map((p) => p.id || '(unnamed)')
    expect(stranded, 'tab-content hoisted out of the left panel').toEqual([])
  })
})
