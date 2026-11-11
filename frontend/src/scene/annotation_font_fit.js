import { rotatedBoxSize } from './annotation_box_math.js'

/** Fit text and the rotated box without changing the user's saved dimensions/font. */
export function fitAnnotationFont(rec, entry, viewport) {
  const width = Math.max(1, viewport.width - 16), height = Math.max(1, viewport.height - 16)
  const signature = `${rec.styleSig}|${width}|${height}`
  if (rec.fontFitSignature === signature) return
  rec.fontFitSignature = signature
  const angle = entry.rotationDeg ?? 0
  const box = rec.box
  rec.el.style.width = ''; rec.el.style.height = ''
  box.style.transform = ''; box.style.position = 'relative'; box.style.left = ''; box.style.top = ''
  box.style.width = ''; box.style.height = ''
  const custom = entry.boxSize
  let limitW = width, limitH = height
  if (custom) {
    const bounds = rotatedBoxSize(custom.w, custom.h, angle)
    const scale = Math.min(1, width / bounds.w, height / bounds.h)
    limitW = custom.w * scale; limitH = custom.h * scale
    box.style.width = `${limitW}px`; box.style.height = `${limitH}px`
  }
  let pixels = Math.max(0.01, Math.min(13 * entry.size, Math.max(width, height)))
  box.style.maxWidth = `${custom ? limitW : Math.min(width, Math.max(280, pixels * 10))}px`
  const apply = () => {
    box.style.fontSize = `${pixels}px`
    const svg = rec.icon.querySelector('svg')
    if (svg) { svg.setAttribute('width', String(18 * pixels / 13)); svg.setAttribute('height', String(18 * pixels / 13)) }
  }
  const style = box.ownerDocument.defaultView.getComputedStyle(box)
  const paddingX = parseFloat(style.paddingLeft || 0) + parseFloat(style.paddingRight || 0) + 4
  const paddingY = parseFloat(style.paddingTop || 0) + parseFloat(style.paddingBottom || 0) + 4
  const fits = () => {
    const occupied = rotatedBoxSize(box.offsetWidth, box.offsetHeight, angle)
    if (!custom) return occupied.w <= width && occupied.h <= height
    const contentW = (rec.text?.scrollWidth ?? 0) + (rec.icon.hidden ? 0 : rec.icon.offsetWidth + 7) + paddingX
    const contentH = Math.max(rec.text?.scrollHeight ?? 0, rec.icon.hidden ? 0 : rec.icon.offsetHeight) + paddingY
    return contentW <= limitW && contentH <= limitH
  }
  apply()
  if (!fits()) {
    // Wrapping makes height nonlinear in font size. Find the largest font that
    // fits instead of shrinking excessively from the first overflowing layout.
    let low = 0, high = pixels
    for (let attempt = 0; attempt < 16; attempt++) {
      pixels = (low + high) / 2; apply()
      if (fits()) low = pixels
      else high = pixels
    }
    pixels = Math.max(0.01, low); apply()
  }
  const w = box.offsetWidth, h = box.offsetHeight
  rec.displaySize = pixels / 13
  rec.boxSize = { w, h }
  rec.size = rotatedBoxSize(w, h, angle)
  rec.el.style.width = `${rec.size.w}px`; rec.el.style.height = `${rec.size.h}px`
  box.style.position = 'absolute'
  box.style.left = `${(rec.size.w - w) / 2}px`; box.style.top = `${(rec.size.h - h) / 2}px`
  box.style.transform = `rotate(${angle}deg)`
}
