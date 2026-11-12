const PAYLOADS = new Set(['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64', 'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'])

/** Source identity without embedding molecular data in the presentation file. */
export async function presentationSourceHash(source) {
  if (!source?.id) return null
  const keys = ['id', 'feature_log', 'feature_log_cursor', 'helices', 'strands', 'crossovers', 'deformations',
    'cluster_transforms', 'overhangs', 'extensions', 'nanoparticles', 'atomistic_reference',
    'instances', 'joints', 'configurations', 'camera_poses', 'annotations', 'view_volumes', 'zoom_volumes']
  const selected = Object.fromEntries(keys.map(k => [k, source[k]]))
  if (selected.joints) selected.joints = selected.joints.map(({ current_value, ...joint }) => joint)
  const text = JSON.stringify(selected, (key, value) => {
    if (PAYLOADS.has(key)) return undefined
    if (value && typeof value === 'object' && !Array.isArray(value)) return Object.fromEntries(Object.keys(value).sort().map(k => [k, value[k]]))
    return value
  })
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
}

/** Read data only. Never execute scripts/styles from an imported HTML file. */
export function readPresentationPackage(html) {
  if (html.length > 512 * 1024 * 1024) throw new Error('Presentation file exceeds 512 MiB.')
  const marker = '<script id="nadoc-presentation-data" type="application/json">'
  const start = html.indexOf(marker), end = start < 0 ? -1 : html.indexOf('</script>', start + marker.length)
  if (start < 0 || end < 0) throw new Error('This file has no reopenable presentation data. Recompile it once with the current NADOC version.')
  const data = JSON.parse(html.slice(start + marker.length, end))
  if (data.version !== 1 || !Array.isArray(data.clips) || !data.clips.length || data.clips.length > 10000) throw new Error('Invalid presentation package.')
  let bytes = 0
  const media = (value, type) => typeof value === 'string' && new RegExp(`^data:${type};base64,[A-Za-z0-9+/=]+$`).test(value)
  for (const clip of data.clips) {
    if (typeof clip.name !== 'string' || !media(clip.video, 'video/webm') || !media(clip.first, 'image/(jpeg|png)') || !media(clip.last, 'image/(jpeg|png)') || !Number.isFinite(clip.duration) || clip.duration <= 0) throw new Error('Invalid presentation video or endpoint image.')
    bytes += clip.video.length * 3 / 4
  }
  if (bytes > 257 * 1024 * 1024) throw new Error('Presentation videos exceed the supported size.')
  const info = data.inspection
  if (info) {
    if (!Array.isArray(info.animation?.keyframes) || (info.clipKeyframeIds ? info.clipKeyframeIds.length !== data.clips.length || info.clipKeyframeIds.some(id => !info.animation.keyframes.some(kf => kf.id === id)) : info.animation.keyframes.length !== data.clips.length) || !Array.isArray(info.ranges) || info.ranges.length !== data.clips.length) throw new Error('Invalid live inspection timeline.')
    let end = info.clipKeyframeIds ? info.ranges[0].start : 0
    info.ranges.forEach((range, i) => {
      if (!Number.isFinite(range.start) || range.start < 0 || !Number.isFinite(range.end) || Math.abs(range.start - end) > 1e-6 || range.end <= range.start || Math.abs(range.end - range.start - data.clips[i].duration) > 1e-6) throw new Error('Invalid live inspection timing.')
      end = range.end
    })
    if (info.sourceHash != null && !/^[a-f0-9]{64}$/.test(info.sourceHash)) throw new Error('Invalid source identity.')
    if (info.initialCamera) {
      const pose = info.initialCamera
      if (!['position', 'up', 'target'].every(key => Array.isArray(pose[key]) && pose[key].length === 3 && pose[key].every(Number.isFinite)) || !(pose.fov > 0 && pose.fov < 180)) throw new Error('Invalid inspection camera.')
    }
  }
  return data
}
