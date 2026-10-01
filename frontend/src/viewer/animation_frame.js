/** Bounded, text-only animation metadata carried with its exact geometry frame. */
export function animationFrame(value) {
  if (!value || !Number.isFinite(value.time) || value.time < 0 || !Number.isFinite(value.duration) || value.duration < value.time || !value.camera) throw new Error('Invalid animation frame')
  let text = null
  if (value.text) {
    const t = value.text
    if (typeof t.text !== 'string' || t.text.length > 2048 || typeof t.fontFamily !== 'string' || t.fontFamily.length > 128 ||
      !Number.isFinite(t.fontSizePx) || t.fontSizePx < 1 || t.fontSizePx > 1000 || !Number.isFinite(t.opacity) || t.opacity < 0 || t.opacity > 1 ||
      typeof t.color !== 'string' || t.color.length > 64 || !['left', 'center', 'right'].includes(t.align)) throw new Error('Invalid animation caption')
    text = { text: t.text, fontFamily: t.fontFamily, fontSizePx: t.fontSizePx, opacity: t.opacity, color: t.color, align: t.align, bold: !!t.bold, italic: !!t.italic }
  }
  return { time: value.time, duration: value.duration, camera: value.camera, text }
}
