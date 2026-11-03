import { initTrajectoryStream } from './trajectory_stream.js'
import { TrajectoryMemoryMap, trajectoryMemory, trajectoryStorageBytes } from './trajectory_memory.js'

function normalizeFrames(result) {
  if (result?.frames) result.frames = result.frames.map(frame =>
    Array.isArray(frame) ? Float64Array.from(frame) : frame)
  return result
}

/** Exact pages are disposable; their source frames remain on disk. */
export async function loadProgressiveTrajectory({ jobId, spec, downloads, metadata,
  signal, onProgress, live, heavy, evict, memory = trajectoryMemory,
  budgetBytes = memory.stats().limitBytes }) {
  const firstPageSize = 8, pageSize = 16
  const firstSpec = { ...spec, frameStart: 0, frameEnd: firstPageSize - 1 }
  let [first, meta] = await Promise.all([
    downloads.get(jobId, firstSpec, { signal, onProgress }), metadata(),
  ])
  downloads.consumed(jobId, firstSpec)
  if (signal?.aborted || !live()) throw new DOMException('cancelled', 'AbortError')
  if (!first?.ready || !first.frames?.length || !meta?.n_frames) throw new Error('No trajectory frames')
  if (!Number.isSafeInteger(meta.n_frames) || meta.n_frames > 1_000_000) throw new Error('Too many trajectory frames to index safely. Select a smaller range.')
  normalizeFrames(first)
  if (trajectoryStorageBytes(first.frames) > budgetBytes) throw new Error('Trajectory page exceeds the memory budget. Select a smaller range.')
  const frames = new Array(meta.n_frames)
  const resp = { ...first, ...meta, frames, n_frames: meta.n_frames,
    total_n_frames: meta.n_frames, frame_start: 0 }
  let seed = first, disposed = false, stream
  first = null // do not retain a second reference to an evicted first page
  let bytesPerFrame = 0
  const pages = new TrajectoryMemoryMap({ memory, maxBytes: budgetBytes, onEvict: start => {
    const end = start === 0 ? firstPageSize : Math.min(start + pageSize, frames.length)
    for (let i = start; i < end; i++) { delete frames[i]; evict?.(i) }
    if (start === 0) seed = null
    stream?.forget(start)
  } })
  const status = () => {
    const buffered = [...pages.values()].reduce((n, page) => n + page.frames.length, 0)
    const bytes = trajectoryStorageBytes([...pages.values()].map(page => page.frames))
    return { buffered, total: meta.n_frames, bytes, complete: buffered === meta.n_frames,
      limited: bytesPerFrame * meta.n_frames > budgetBytes ||
        (buffered < meta.n_frames && memory.stats().bytes + pageSize * bytesPerFrame > memory.stats().limitBytes) }
  }
  const isLive = () => !disposed && !signal?.aborted && live()
  const dispose = () => {
    disposed = true; seed = null
    for (const start of [...pages.keys()]) pages.evict(start)
    signal?.removeEventListener('abort', dispose)
  }
  stream = initTrajectoryStream({ total: meta.n_frames, pageSize, firstPageSize, live: isLive,
    load: async (start, end) => {
      const range = { ...spec, frameStart: start, frameEnd: end }
      const result = start === 0 && seed ? seed : await downloads.get(jobId, range, { signal })
      if (start === 0) seed = null
      downloads.consumed(jobId, range)
      if (!isLive()) return null
      if (!result?.ready || result.frames?.length !== end - start + 1) throw new Error('Incomplete trajectory page')
      normalizeFrames(result)
      for (const frame of result.frames) if (!ArrayBuffer.isView(frame)) throw new Error('Invalid trajectory frame')
      const pageBytes = trajectoryStorageBytes(result.frames)
      if (pageBytes > budgetBytes) throw new Error('Trajectory page exceeds the memory budget. Select a smaller range.')
      bytesPerFrame = Math.max(bytesPerFrame, pageBytes / result.frames.length)
      await heavy?.(start, end)
      return result
    },
    apply: async (page, start) => {
      if (!isLive()) return
      pages.set(start, page)
      page.frames.forEach((frame, i) => { frames[start + i] = frame })
    },
  })
  // Charge the seed while it is waiting for its heavy representation.
  pages.set(0, seed)
  seed.frames.forEach((frame, i) => { frames[i] = frame })
  bytesPerFrame = trajectoryStorageBytes(seed.frames) / seed.frames.length
  signal?.addEventListener('abort', dispose, { once: true })
  return { resp, ...stream, status, dispose,
    fill: async (onProgress = () => {}) => {
      const report = () => { if (isLive()) onProgress(status()) }
      report()
      await stream.fill({ canContinue: () => {
        const next = pageSize * bytesPerFrame
        return status().bytes + next <= budgetBytes && memory.stats().bytes + next <= memory.stats().limitBytes
      }, onProgress: report })
      report()
      return status()
    },
  }
}
