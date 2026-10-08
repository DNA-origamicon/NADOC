/** Feature-log ticks in chronological order: initial (-2), entries, all (-1).
 * Null pins inherit the previous state. Routing children remain one authored tick.
 */
export function featurePath(from, to, count) {
  const rank = index => index === -2 ? 0 : index === -1 ? count : Math.max(0, Math.min(count, index + 1))
  const a = rank(from), b = rank(to)
  if (a === b) return [from, to]
  const direction = Math.sign(b - a), path = [from]
  for (let r = a + direction; r !== b; r += direction) path.push(r === 0 ? -2 : r - 1)
  path.push(to)
  return path
}

/** Adjacent states and local blend; camera and other channels keep global progress. */
export function featurePair(path, progress) {
  const scaled = Math.max(0, Math.min(1, progress)) * (path.length - 1)
  const index = Math.min(path.length - 2, Math.floor(scaled))
  return { from: path[index], to: path[index + 1], t: scaled - index }
}

export function featureBakePositions(animation, live, count) {
  const positions = new Set([live])
  let previous = live
  for (const keyframe of animation.keyframes) {
    const next = keyframe.feature_log_index ?? previous
    const path = keyframe.transition_duration_s > 0 && !keyframe.trajectory_job_id
      ? featurePath(previous, next, count) : [next]
    for (const index of path) positions.add(index)
    previous = next
  }
  return [...positions]
}

/** A finite-FPS export must give every intermediate operation a sample.
 * Easing can move twice as fast as linear in the existing supported curves.
 */
export function assertFeatureSampling(segments, fps) {
  for (const segment of segments) {
    const steps = (segment.featurePath?.length ?? 1) - 1
    const seconds = segment.transEnd - segment.startT
    if (steps <= 1 || seconds <= 0 || segment.trajectory) continue
    const speed = segment.easing === 'linear' ? 1 : 2
    const requiredFps = Math.ceil(steps * speed / seconds)
    if (fps < requiredFps) throw new Error(
      `Build transition crosses ${steps} steps in ${seconds.toFixed(2)}s. Use at least ${requiredFps} fps or lengthen the transition to show every step.`)
  }
}

/** Authoring metadata can refresh while preparing. Only model/history changes
 * invalidate the bake; comparing Design object identity rejects valid refreshes.
 */
export function sameFeatureSource(a, b) {
  const payloadKeys = new Set(['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64',
    'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'])
  const equal = (x, y, key) => {
    // Lightweight history responses omit bodies or use a presence sentinel.
    // Downloading those bodies does not change the operation being animated.
    if (payloadKeys.has(key) && (x == null || x === '' || x === '1')) return true
    if (x === y) return true
    if (!x || !y || typeof x !== 'object' || typeof y !== 'object') return false
    const keys = new Set([...Object.keys(x), ...Object.keys(y)])
    return [...keys].every(k => equal(x[k], y[k], k))
  }
  return a?.id === b?.id && ['feature_log', 'helices', 'strands', 'crossovers',
    'deformations', 'cluster_transforms', 'overhangs', 'extensions', 'nanoparticles']
    .every(key => equal(a?.[key], b?.[key]))
}
