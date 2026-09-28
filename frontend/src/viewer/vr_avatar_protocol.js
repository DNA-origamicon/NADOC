import { validateVRUI } from './vr_ui_protocol.js'
/** Transient tracking and native UI drawing packet; no credentials or document edits. */
export function validateVRAvatar(value) {
  if (value === null) return null
  const vector = (v, n, limit) => Array.isArray(v) && v.length === n && v.every(x => Number.isFinite(x) && Math.abs(x) <= limit)
  const pose = p => p && vector(p.position, 3, 1000) && vector(p.orientation, 4, 1.001) && Math.abs(Math.hypot(...p.orientation)-1) < .001
  if (!value || value.schema !== 1 || !vector(value.trackingToSource, 16, 1e9) || !pose(value.head) ||
      !Array.isArray(value.hands) || value.hands.length !== 2 || !value.hands.every(p => p === null || pose(p))) throw Error('Invalid VR presenter pose')
  const m = value.trackingToSource, cols = [m.slice(0,3),m.slice(4,7),m.slice(8,11)]
  const scale = Math.hypot(...cols[0]), dot = (a,b) => a.reduce((sum,x,i) => sum+x*b[i],0)
  if (scale < 1e-8 || scale > 1e8 || m[3] !== 0 || m[7] !== 0 || m[11] !== 0 || m[15] !== 1 ||
      cols.some(c => Math.abs(Math.hypot(...c)/scale-1) > .001) ||
      Math.abs(dot(cols[0],cols[1])) > scale*scale*.001 || Math.abs(dot(cols[0],cols[2])) > scale*scale*.001 || Math.abs(dot(cols[1],cols[2])) > scale*scale*.001) throw Error('Invalid VR presenter transform')
  const copy = p => p && ({ position: [...p.position], orientation: [...p.orientation] })
  return { schema: 1, trackingToSource: [...m], head: copy(value.head), hands: value.hands.map(copy), ...(value.ui == null ? {} : {ui:validateVRUI(value.ui)}) }
}
