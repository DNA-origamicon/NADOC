export function selectedSourceHandle(track, origin) {
  const identity = track?.getCaptureHandle?.()
  if (track?.getSettings().displaySurface !== 'browser' || identity?.origin !== origin ||
      !/^nadoc-capture-v1:[0-9a-f-]{36}$/.test(identity?.handle || '')) {
    throw new Error('Select a NADOC 3D viewer or cadnano editor tab. Other tabs, windows, and screens cannot be captured. Reload older NADOC tabs first.')
  }
  return identity.handle
}

export function verifySource(track, handle, origin) {
  const identity = track?.getCaptureHandle?.()
  if (!handle || track?.getSettings().displaySurface !== 'browser' || identity?.handle !== handle || identity?.origin !== origin) {
    throw new Error('Select the original NADOC browser tab. Other tabs, windows, and screens cannot be captured.')
  }
}

export function outputSize(width, height, resolution) {
  if (resolution === 'native') return [width, height]
  const [w, h] = resolution.split('x').map(Number)
  return [w, h]
}

// Preserve the complete window at every output aspect ratio.
export function drawFrame(ctx, video, width, height) {
  const scale = Math.min(width / video.videoWidth, height / video.videoHeight)
  const w = video.videoWidth * scale, h = video.videoHeight * scale
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, width, height)
  ctx.drawImage(video, (width - w) / 2, (height - h) / 2, w, h)
}
