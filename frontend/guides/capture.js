import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { DEFAULT_GUIDE_REPRESENTATION } from './model.js'

// Guide annotations are presentation only. All authoring goes through real UI input.
export async function createGuide(page, directory, title, { feature = '' } = {}) {
  await mkdir(directory, { recursive: true })
  const steps = []
  const sections = []
  let section = null
  async function capture(caption, point = null) {
    await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
    if (await page.locator('.toast-message').filter({ hasText: 'Selection: D = dimensions' }).count()) {
      throw new Error('Selection startup hint must not appear in guide screenshots')
    }
    const display = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const current = document.getElementById('menu-view-detail-full')?.parentElement?.querySelector('.is-checked')
      return { representation: current?.id.replace(/^menu-view-(?:detail-|atomistic-)?/, '') ?? null,
        overrides: store.getState().currentDesign?.representation_overrides?.length ?? 0 }
    })
    if (feature !== 'representations' && (display.representation !== DEFAULT_GUIDE_REPRESENTATION || display.overrides !== 0)) {
      throw new Error(`Guide screenshots require Full representation without regional overrides; got ${JSON.stringify(display)}`)
    }
    const number = steps.length + 1
    await page.evaluate(({ number, point }) => {
      document.getElementById('guide-click-marker')?.remove()
      if (!point) return
      const ns = 'http://www.w3.org/2000/svg'
      const marker = document.createElementNS(ns, 'svg')
      marker.id = 'guide-click-marker'
      Object.assign(marker.style, { position: 'fixed', inset: '0', width: '100vw', height: '100vh',
        zIndex: '2147483647', pointerEvents: 'none', overflow: 'visible' })
      const x = Math.max(32, Math.min(innerWidth - 32, point.x + (point.dx ?? -94)))
      const y = Math.max(32, Math.min(innerHeight - 32, point.y + (point.dy ?? -62)))
      const angle = Math.atan2(point.y - y, point.x - x)
      const add = (tag, attrs, text) => {
        const element = document.createElementNS(ns, tag)
        for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value)
        if (text != null) element.textContent = text
        marker.append(element)
      }
      const start = { x: x + 22 * Math.cos(angle), y: y + 22 * Math.sin(angle) }
      if (point.end) {
        add('rect', { x: Math.min(point.x, point.end.x), y: Math.min(point.y, point.end.y),
          width: Math.abs(point.end.x - point.x), height: Math.abs(point.end.y - point.y),
          fill: 'none', stroke: '#ffd54a', 'stroke-width': 2, 'stroke-dasharray': '7 5' })
      }
      add('line', { x1: start.x, y1: start.y, x2: point.x, y2: point.y, stroke: '#111827', 'stroke-width': 7 })
      add('line', { x1: start.x, y1: start.y, x2: point.x, y2: point.y, stroke: '#ffd54a', 'stroke-width': 3 })
      const wing = offset => `${point.x - 14 * Math.cos(angle + offset)},${point.y - 14 * Math.sin(angle + offset)}`
      add('polygon', { points: `${point.x},${point.y} ${wing(0.48)} ${wing(-0.48)}`, fill: '#ffd54a', stroke: '#111827', 'stroke-width': 1 })
      add('rect', { x: x - 20, y: y - 16, width: 40, height: 32, rx: 5, fill: '#ffd54a', stroke: '#111827', 'stroke-width': 2 })
      add('text', { x, y: y + 6, 'text-anchor': 'middle', fill: '#111827', 'font-family': 'sans-serif', 'font-size': 18, 'font-weight': 'bold' }, number)
      document.body.append(marker)
    }, { number, point })
    const file = `${String(number).padStart(2, '0')}.png`
    try {
      await page.screenshot({ path: path.join(directory, file) })
      steps.push({ number, caption, file, point, section, annotation: point ? 'numbered-arrow' : null, representation: display.representation })
    } finally {
      await page.evaluate(() => document.getElementById('guide-click-marker')?.remove())
    }
  }
  async function click(locator, caption) {
    await locator.click({ trial: true })
    const box = await locator.boundingBox()
    if (!box) throw new Error(`Guide target missing: ${caption}`)
    await capture(caption, { x: box.x - 3, y: box.y + box.height / 2 })
    await locator.click()
  }
  return {
    capture, click,
    section(title, body = '') { section = title; sections.push({ title, body }) },
    async pointAt(locator, caption) {
      await locator.scrollIntoViewIfNeeded()
      const box = await locator.boundingBox()
      if (!box) throw new Error(`Guide target missing: ${caption}`)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await capture(caption, { x: box.x - 3, y: box.y + box.height / 2 })
    },
    async clickPoint(point, caption, options = {}) {
      await page.mouse.move(point.x, point.y)
      await capture(caption, point)
      await page.mouse.click(point.x, point.y, options)
    },
    async finish() {
      await writeFile(path.join(directory, 'steps.json'), JSON.stringify({ title, representationPolicy: feature === 'representations' ? 'lesson' : DEFAULT_GUIDE_REPRESENTATION, sections, steps }, null, 2))
    },
  }
}
