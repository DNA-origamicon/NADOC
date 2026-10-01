import { it, expect, vi } from 'vitest'
import { mountViewerScreenshot } from './viewer_screenshot.js'
it('renders immediately and saves only the scene canvas over its background', async () => {
  document.body.innerHTML = '<main><canvas width="800" height="600"></canvas><button>UI</button><svg>Drawing overlay</svg></main>'
  const canvas = document.querySelector('canvas'), order = [], drawImage = vi.fn(() => order.push('copy'))
  const ctx = { fillRect: vi.fn(), drawImage }
  const context = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx)
  const blob = new Blob(['image'], { type: 'image/png' })
  const encode = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (callback) { expect(this.width).toBe(800); expect(this.height).toBe(600); callback(blob) })
  const download = vi.fn()
  const api = mountViewerScreenshot({ parent: document.body, canvas, download, viewer: { current: { data: { background: '#123456' } }, runtime: { renderNow: () => order.push('render') } } })
  document.querySelector('[data-screenshot]').click()
  await vi.waitFor(() => expect(download).toHaveBeenCalledWith(blob))
  expect(order).toEqual(['render', 'copy']); expect(ctx.fillStyle).toBe('#123456')
  expect(drawImage).toHaveBeenCalledExactlyOnceWith(canvas, 0, 0)
  api.dispose(); context.mockRestore(); encode.mockRestore()
})
