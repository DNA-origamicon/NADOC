import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

// Read-only app exercise: no document, workspace part, job, or viewer is created.
// Optional PNG evidence is retained only under the explicit development path.
test('VR view tablet keeps normal and long error messages inside its footer', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('#view-tools', { state: 'attached' })
  const cases = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { captureVRView, encodeVRView } = await import('/src/scene/vr_view_tools.js')
    const { viewToolMessageLines } = await import('/src/scene/vr_view_tools_panel.js')
    const results = []
    for (const [name, message] of [
      ['normal', 'Left quiver: show / hide. Right quiver: scissors.'],
      ['long-error', 'View unavailable: ' + 'An export failed while retaining the previous displayed view. '.repeat(20)],
      ['unbroken-error', 'W'.repeat(800)],
    ]) {
      const view = await captureVRView(new THREE.Scene(), document, message, true)
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = 768
      const context = canvas.getContext('2d')
      const pixels = context.createImageData(768, 768)
      for (let y = 0; y < 768; y++) pixels.data.set(view.pixels.subarray(y * 2048 * 4, (y * 2048 + 768) * 4), y * 768 * 4)
      context.putImageData(pixels, 0, 0)
      context.font = '18px sans-serif'
      const lines = viewToolMessageLines(context, message)
      let borderInk = 0, footerInk = 0
      for (let y = 620; y < 768; y++) for (let x = 410; x < 768; x++) {
        const i = (y * 768 + x) * 4
        const ink = pixels.data[i] > 100 || pixels.data[i + 1] > 100 || pixels.data[i + 2] > 100
        if (ink) { footerInk++; if (x >= 744 || y >= 744) borderInk++ }
      }
      const stream = await new Promise(resolve => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result.split(',')[1])
        reader.readAsDataURL(new Blob([encodeVRView(view, 1)]))
      })
      results.push({ name, lines, widths: lines.map(line => context.measureText(line).width), borderInk, footerInk,
        png: canvas.toDataURL('image/png'), stream })
    }
    return results
  })
  const output = process.env.NADOC_VR_FORMATTING_EVIDENCE
  if (output) {
    fs.mkdirSync(output, { recursive: true })
    for (const item of cases) {
      fs.writeFileSync(path.join(output, `view-tablet-${item.name}.png`), Buffer.from(item.png.split(',')[1], 'base64'))
      fs.writeFileSync(path.join(output, `view-tablet-${item.name}.bin`), Buffer.from(item.stream, 'base64'))
    }
    fs.writeFileSync(path.join(output, 'view-tablet-layout.json'), JSON.stringify(cases.map(({ png, stream, ...item }) => item), null, 2))
  }
  for (const item of cases) {
    expect(item.lines.length).toBeLessThanOrEqual(4)
    expect(item.widths.every(width => width <= 326)).toBe(true)
    expect(item.borderInk).toBe(0)
    expect(item.footerInk).toBeGreaterThan(100)
    if (item.name !== 'normal') expect(item.lines.at(-1)).toMatch(/\.\.\.$/)
  }
})
