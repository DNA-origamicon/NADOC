/** Preserve dense moving molecular detail as resolution/frame rate increase. */
export function videoBitrate(width, height, fps) {
  if (![width, height, fps].every(v => Number.isFinite(v) && v > 0)) throw new Error('Invalid video dimensions or frame rate')
  return Math.round(Math.max(8_000_000, Math.min(120_000_000, width * height * fps * .2)))
}
