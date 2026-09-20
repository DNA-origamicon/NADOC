import { initTrajectoryStream } from './trajectory_stream.js'

// JSON fallback arrays have no byteLength. Float64 preserves their numeric
// precision while giving both transports the same explicit storage accounting.
function normalizeFrames(result) {
  if (result?.frames) result.frames = result.frames.map(frame =>
    Array.isArray(frame) ? Float64Array.from(frame) : frame)
  return result
}

/** Open a trajectory without making its length the startup cost. Frame-count and
 * stage metadata cover the entire selection; coordinate pages remain exact. */
export async function loadProgressiveTrajectory({ jobId, spec, downloads, metadata,
  signal, onProgress, live, heavy, evict, budgetBytes = 1536 * 1024 * 1024 }) {
  const firstPageSize = 8, pageSize = 16
  const firstSpec = { ...spec, frameStart: 0, frameEnd: firstPageSize - 1 }
  const [first, meta] = await Promise.all([
    downloads.get(jobId, firstSpec, { signal, onProgress }), metadata(),
  ])
  downloads.consumed(jobId, firstSpec)
  if (!first?.ready || !first.frames?.length || !meta?.n_frames) throw new Error('No trajectory frames')
  normalizeFrames(first)
  const frames = new Array(meta.n_frames)
  first.frames.forEach((frame, i) => { frames[i] = frame })
  const resp = { ...first, ...meta, frames, n_frames: meta.n_frames,
    total_n_frames: meta.n_frames, frame_start: 0 }
  let seed = first
  const pages = []
  let bytesPerFrame = 0, buffered = 0, bytes = 0
  const status = () => ({ buffered, total: meta.n_frames, bytes,
    complete: buffered === meta.n_frames, limited: bytesPerFrame * meta.n_frames > budgetBytes })
  const stream = initTrajectoryStream({ total: meta.n_frames, pageSize, firstPageSize, live,
    load: async (start, end) => {
      const range = { ...spec, frameStart: start, frameEnd: end }
      const [result, heavyBytes] = await Promise.all([
        start === 0 && seed ? seed : downloads.get(jobId, range, { signal }),
        heavy(start, end),
      ])
      if (start === 0) seed = null
      downloads.consumed(jobId, range)
      if (!result?.ready || result.frames?.length !== end - start + 1) throw new Error('Incomplete trajectory page')
      normalizeFrames(result)
      for (const frame of result.frames) {
        if (!ArrayBuffer.isView(frame)) throw new Error('Invalid trajectory frame')
        bytesPerFrame = Math.max(bytesPerFrame, frame.byteLength + (heavyBytes || 0))
      }
      return result
    },
    apply: async (page, start, end) => {
      if (!live()) return
      page.frames.forEach((frame, i) => { frames[start + i] = frame })
      pages.push([start, end])
      buffered += end - start + 1
      bytes = buffered * bytesPerFrame
      while (bytes > budgetBytes && pages.length > 1) {
        const [lo, hi] = pages.shift()
        for (let i = lo; i <= hi; i++) { delete frames[i]; evict(i) }
        stream.forget(lo)
        buffered -= hi - lo + 1
        bytes = buffered * bytesPerFrame
      }
    },
  })
  return { resp, ...stream, status,
    fill: async (onProgress = () => {}) => {
      const report = () => { if (live()) onProgress(status()) }
      report()
      await stream.fill({ canContinue: () => !status().limited || bytes + pageSize * bytesPerFrame <= budgetBytes,
        onProgress: report })
      report()
      return status()
    },
  }
}
