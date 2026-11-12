import { encodeWebM } from './encode_webm.js'
import { editorVideoFrame } from './export_video.js'
import { presentationAnimation, presentationHTML } from './compiled_presentation.js'
import { assertPlacementExportSafe } from '../viewer/placement_scene_guard.js'
import { withMediaExport } from '../shared/media_export_activity.js'

// Embedded videos expand by 4/3 in HTML; cap output before browser string/heap exhaustion.
const MAX_VIDEO_BYTES = 256 * 1024 * 1024

export function compilePresentation(options) {
  return withMediaExport(() => compile(options))
}

async function compile({ animation, player, renderer, scene, camera, resolution = '1080p', playOptions = {}, inspection = {}, keyframeId = null, signal, onPrepared = () => {}, onProgress = () => {} }) {
  assertPlacementExportSafe(scene)
  const fps = Math.max(1, Math.min(60, Number(animation.fps) || 30))
  const selected = keyframeId == null ? -1 : animation.keyframes.findIndex(kf => kf.id === keyframeId)
  if (keyframeId != null && selected < 0) throw new Error('Keyframe no longer exists.')
  const source = presentationAnimation({ ...animation, keyframes: selected < 0 ? animation.keyframes : animation.keyframes.slice(0, selected + 1) }, fps)
  const targets = selected < 0 ? source.keyframes : [source.keyframes[selected]]
  if (!source.keyframes.length) throw new Error('Add a keyframe before compiling.')
  const saved = { bounce: player.getBounce(), loop: player.getLoopMode(), poses: player.getDisablePoses(),
    width: renderer.domElement.width, height: renderer.domElement.height, ratio: renderer.getPixelRatio(), aspect: camera.aspect }
  const cancel = () => player.cancelBake?.()
  signal?.addEventListener('abort', cancel)
  const clips = [], ranges = []; let bytes = 0
  try {
    signal?.throwIfAborted()
    player.setBounce(false); player.setDisablePoses(false)
    onProgress({ phase: 'prepare', total: targets.length })
    await player.play(source, { ...playOptions, holdKeyframeText: true })
    signal?.throwIfAborted()
    player.pause()
    player.assertExportSampling?.(fps)
    const [w, h] = resolution === '720p' ? [1280, 720] : [1920, 1080]
    renderer.setPixelRatio(1); renderer.setSize(w, h, false)
    camera.aspect = w / h; camera.updateProjectionMatrix()
    const canvas = Object.assign(document.createElement('canvas'), { width: w, height: h })
    const ctx = canvas.getContext('2d')
    const render = editorVideoFrame({ player, renderer, scene, camera, ctx, canvas: renderer.domElement, w, h })
    for (const [index, keyframe] of targets.entries()) {
      signal?.throwIfAborted()
      const range = player.getKeyframeRange(keyframe.id)
      if (!range || range.end <= range.start) throw new Error(`Keyframe ${index + 1} has no playable range`)
      const name = keyframe.name || keyframe.text || `Keyframe ${index + 1}`
      const report = detail => onProgress({ index, total: targets.length, name, ...detail })
      report({ phase: 'capture', done: 0, frames: Math.ceil((range.end - range.start) * fps) })
      let first
      const blob = await encodeWebM({ canvas, fps, totalDur: range.end - range.start, signal,
        renderFrame: async t => {
          await render(range.start + t)
          if (t === 0) first = canvas.toDataURL('image/jpeg', 0.9)
        },
        onProgress: (_, { frame, frames }) => report({ phase: 'capture', done: frame, frames }),
        onPhase: phase => { if (phase === 'encode') report({ phase: 'encode' }) },
      })
      bytes += blob.size
      if (bytes > MAX_VIDEO_BYTES) throw new Error('Presentation exceeds 256 MiB of video. Compile shorter animations as separate presentations.')
      // Exact endpoints are separately retained: video sampling need not land on the boundary.
      await render(range.end); signal?.throwIfAborted()
      const last = canvas.toDataURL('image/jpeg', 0.9)
      const video = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result)
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(blob)
      })
      signal?.throwIfAborted()
      clips.push({ name, first, last, video, duration: range.end - range.start })
      ranges.push({ ...range })
      report({ phase: 'complete', bytes })
    }
    assertPlacementExportSafe(scene)
    onProgress({ phase: 'package', total: clips.length })
    signal?.throwIfAborted()
    const prepared = { ...inspection, initialJointValues: playOptions.liveJointValues ?? null, animation: source, ranges, clipKeyframeIds: targets.map(kf => kf.id) }
    const blob = new Blob([presentationHTML(animation.name || 'Presentation', clips, prepared)], { type: 'text/html' })
    onPrepared(prepared)
    return blob
  } finally {
    signal?.removeEventListener('abort', cancel)
    player.stop()
    player.setBounce(saved.bounce); player.setLoopMode(saved.loop); player.setDisablePoses(saved.poses)
    renderer.setPixelRatio(saved.ratio)
    renderer.setSize(saved.width / saved.ratio, saved.height / saved.ratio, false)
    camera.aspect = saved.aspect; camera.updateProjectionMatrix()
  }
}
