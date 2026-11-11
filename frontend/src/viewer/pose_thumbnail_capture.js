/** Read the current rendered view in the same task as rendering (WebGL clears later). */
export function capturePoseThumbnail(canvas, render) {
  render()
  const image = canvas.ownerDocument.createElement('canvas')
  const scale = Math.min(240 / Math.max(1, canvas.width), 150 / Math.max(1, canvas.height))
  image.width = Math.max(1, Math.round(canvas.width * scale))
  image.height = Math.max(1, Math.round(canvas.height * scale))
  const context = image.getContext('2d')
  context.fillStyle = getComputedStyle(canvas.parentElement).backgroundColor || '#15151b'
  context.fillRect(0, 0, image.width, image.height)
  context.drawImage(canvas, 0, 0, image.width, image.height)
  return image.toDataURL('image/jpeg', 0.75)
}
