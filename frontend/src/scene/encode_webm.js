/** Offline encoding: presentation timestamps come from the animation clock,
 * never from how long rendering, GPU readback, or background loading took.
 * CanvasSource queues native encoding (up to its bounded backpressure threshold)
 * while subsequent frames render; no frames are dropped to catch up.
 * Hardware preference is capability-tested, not a guarantee of GPU execution.
 */
export async function encodeWebM({ canvas, fps, totalDur, renderFrame, onProgress, onPhase, signal }) {
  const { Output, WebMOutputFormat, BufferTarget, CanvasSource, getFirstEncodableVideoCodec, canEncodeVideo } = await import('mediabunny')
  const dimensions = { width: canvas.width, height: canvas.height, frameRate: fps, bitrate: 8_000_000 }
  let codec = null, hardwareAcceleration = 'prefer-hardware'
  for (const candidate of ['vp9', 'vp8']) {
    if (await canEncodeVideo(candidate, { ...dimensions, hardwareAcceleration })) { codec = candidate; break }
  }
  if (!codec) {
    hardwareAcceleration = 'no-preference'
    codec = await getFirstEncodableVideoCodec(['vp9', 'vp8'], dimensions)
  }
  if (!codec) throw new Error('Frame-accurate WebM export needs WebCodecs VP9 or VP8 support. Use Chrome/Edge or export GIF.')
  const output = new Output({ format: new WebMOutputFormat(), target: new BufferTarget() })
  const source = new CanvasSource(canvas, { codec, bitrate: dimensions.bitrate, hardwareAcceleration, latencyMode: 'quality' })
  output.addVideoTrack(source, { frameRate: fps })
  const frames = Math.ceil(totalDur * fps)
  try {
    await output.start()
    for (let i = 0; i < frames; i++) {
      signal?.throwIfAborted()
      const time = i / fps
      await renderFrame(time)
      signal?.throwIfAborted()
      await source.add(time, Math.min(1 / fps, totalDur - time))
      onProgress?.((i + 1) / frames, { frame: i + 1, frames })
      onPhase?.('capture', { done: i + 1, total: frames })
    }
    onPhase?.('encode')
    await output.finalize()
    signal?.throwIfAborted()
    return new Blob([output.target.buffer], { type: 'video/webm' })
  } catch (error) {
    if (output.state !== 'finalized') await output.cancel()
    throw error
  }
}
