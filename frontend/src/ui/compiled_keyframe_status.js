import { presentationSourceHash } from '../scene/presentation_package.js'
import { presentationAnimation } from '../scene/compiled_presentation.js'

export function compiledKeyframeSignature(animation, id) {
  const index = animation?.keyframes?.findIndex(kf => kf.id === id) ?? -1
  if (index < 0) return null
  const fps = Math.max(1, Math.min(60, Number(animation.fps) || 30))
  const normalized = presentationAnimation(animation, fps)
  return JSON.stringify([animation.id, fps, normalized.keyframes.slice(0, index + 1)])
}

/** Evidence of available video, kept separate from the live trajectory cache. */
export function initCompiledKeyframeStatus({ getAnimation, getSource, onChange = () => {}, hashSource = presentationSourceHash }) {
  const records = new Map()
  let generation = 0, states = new Map(), source = null, hashWork = null
  const key = (sourceId, animationId, id) => JSON.stringify([sourceId, animationId, id])
  const notify = () => onChange(new Map(states))
  async function refresh() {
    const token = ++generation, animation = getAnimation(), current = getSource()
    if (!hashWork || source !== current) { source = current; hashWork = Promise.resolve().then(() => hashSource(current)) }
    const rows = (animation?.keyframes || []).filter(kf => kf.trajectory_job_id)
    states = new Map(rows.map(kf => [kf.id, records.has(key(current?.id, animation.id, kf.id)) ? 'checking' : 'none']))
    notify()
    try {
      const hash = await hashWork
      if (token !== generation) return
      states = new Map(rows.map(kf => {
        const items = records.get(key(current?.id, animation.id, kf.id)) || []
        const signature = compiledKeyframeSignature(animation, kf.id)
        return [kf.id, items.some(item => item.hash === hash && item.signature === signature) ? 'ready' : items.length ? 'stale' : 'none']
      }))
    } catch { if (token !== generation) return; states = new Map(rows.map(kf => [kf.id, 'none'])) }
    notify()
  }
  return {
    refresh,
    record(info) {
      if (!info?.animation) return
      for (const id of info.clipKeyframeIds || info.animation.keyframes.map(kf => kf.id)) {
        const entry = key(info.sourceId, info.animation.id, id)
        const items = records.get(entry) || []
        const signature = compiledKeyframeSignature(info.animation, id)
        records.set(entry, [...items.filter(item => item.signature !== signature || item.hash !== info.sourceHash), { signature, hash: info.sourceHash }].slice(-8))
      }
      void refresh()
    },
    dispose() { generation++; records.clear() },
  }
}
