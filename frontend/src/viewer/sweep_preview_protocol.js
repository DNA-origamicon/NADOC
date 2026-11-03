import { validateVRAvatar } from './vr_avatar_protocol.js'

// Compact bounded geometry, independent of native UI textures and avatar visibility.
export function validateSweepPreview(value) {
  if (value === null) return null
  const fail = () => { throw new Error('Invalid sweep preview') }
  const vector = (v, n) => {
    if (!Array.isArray(v) || v.length !== n || v.some(x => !Number.isFinite(x) || Math.abs(x) > 1e5)) fail()
    return [...v]
  }
  const list = (v, n, max) => { if (!Array.isArray(v) || v.length > max) fail(); return v.map(p => vector(p, n)) }
  if (!value || !Number.isFinite(value.radius) || value.radius <= 0 || value.radius > .1) fail()
  const matrix = m => validateVRAvatar({schema:1,trackingToSource:m,head:{position:[0,0,0],orientation:[0,0,0,1]},hands:[null,null]}).trackingToSource
  const nodes = list(value.nodes, 3, 256), frames = list(value.frames, 6, 256)
  if (!nodes.length || frames.length !== nodes.length || !Number.isInteger(value.selected) || value.selected < 0 || value.selected >= nodes.length) fail()
  if (frames.some(f => Math.abs(Math.hypot(...f.slice(0,3))-1) > .01 || Math.abs(Math.hypot(...f.slice(3))-1) > .01 || Math.abs(f[0]*f[3]+f[1]*f[4]+f[2]*f[5]) > .01)) fail()
  return {trackingToSource:matrix(value.trackingToSource),model:matrix(value.model),radius:value.radius,selected:value.selected,nodes,frames,
    path:list(value.path,3,512),outline:list(value.outline,2,128),cells:list(value.cells,2,256)}
}
