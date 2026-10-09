import * as THREE from 'three'

const Z = new THREE.Vector3(0, 0, 1), X = new THREE.Vector3(1, 0, 0)
export const SWEEP_LIVE_BUDGET = 4096
const vector = p => new THREE.Vector3(...p)
export const sweepFrameQuaternion = rows => new THREE.Quaternion().setFromRotationMatrix(
  new THREE.Matrix4().set(...rows[0],0,...rows[1],0,...rows[2],0,0,0,0,1))

/** Display-only chord-length cubic, matching VR's bounded local path sampler.
 * Natural boundaries, clamped attachment tangent, and authored Hermite directions.
 * Server geometry and validation remain authoritative. */
export function sampleLiveSweep(values, orientations = [], basis = new THREE.Quaternion(), initial = null, count = 128) {
  const n = values.length
  if (orientations.some(a => a != null && (a.length !== 3 || !a.every(Number.isFinite)))) return null
  if (n < 2 || n > 256 || values.some(p => p.length !== 3 || !p.every(Number.isFinite))) return null
  const p = values.map(vector), knots = [0], second = p.map(() => new THREE.Vector3())
  const lower = new Float64Array(n), diagonal = new Float64Array(n), upper = new Float64Array(n)
  for (let i = 1; i < n; i++) {
    const h = p[i].distanceTo(p[i-1]); if (h < 1e-6) return null
    knots.push(knots[i-1]+h)
  }
  diagonal[0] = diagonal[n-1] = 1
  if (initial) {
    const h = knots[1]; diagonal[0] = 2*h; upper[0] = h
    second[0].copy(p[1]).sub(p[0]).divideScalar(h).sub(initial).multiplyScalar(6)
  }
  for (let i = 1; i < n-1; i++) {
    const a = knots[i]-knots[i-1], b = knots[i+1]-knots[i]
    lower[i] = a; diagonal[i] = 2*(a+b); upper[i] = b
    second[i].copy(p[i+1]).sub(p[i]).divideScalar(b)
      .sub(p[i].clone().sub(p[i-1]).divideScalar(a)).multiplyScalar(6)
  }
  for (let i = 1; i < n; i++) {
    const factor = lower[i]/diagonal[i-1]
    diagonal[i] -= factor*upper[i-1]; second[i].addScaledVector(second[i-1], -factor)
  }
  second[n-1].divideScalar(diagonal[n-1])
  for (let i = n-2; i >= 0; i--) second[i].addScaledVector(second[i+1], -upper[i]).divideScalar(diagonal[i])
  const authored = p.map((_, i) => orientations[i] == null ? null : basis.clone().multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(...orientations[i].map(THREE.MathUtils.degToRad), 'YXZ'))))
  const controlled = authored.some(Boolean)
  const derivatives = p.map((_, i) => {
    const j = Math.min(i,n-2), h = knots[j+1]-knots[j]
    const d = p[j+1].clone().sub(p[j]).divideScalar(h)
      .addScaledVector(second[j], (i === n-1 ? 1 : -2)*h/6)
      .addScaledVector(second[j+1], (i === n-1 ? 2 : -1)*h/6)
    return authored[i] ? Z.clone().applyQuaternion(authored[i]).multiplyScalar(Math.max(1,d.length())) : d
  })
  const times = [...new Set([...knots, ...Array.from({length:count}, (_,i) => knots[n-1]*i/(count-1))])].sort((a,b)=>a-b)
  const positions = [], tangents = [], arc = [0], frames = []
  let span = 0
  for (const t of times) {
    while (span+2 < n && knots[span+1] < t) span++
    const h = knots[span+1]-knots[span], b = (t-knots[span])/h, a = 1-b
    let pos, d
    if (controlled) {
      const t2 = b*b, t3 = t2*b
      pos = p[span].clone().multiplyScalar(2*t3-3*t2+1).addScaledVector(p[span+1],-2*t3+3*t2)
        .addScaledVector(derivatives[span],(t3-2*t2+b)*h).addScaledVector(derivatives[span+1],(t3-t2)*h)
      d = p[span].clone().multiplyScalar((6*t2-6*b)/h).addScaledVector(p[span+1],(-6*t2+6*b)/h)
        .addScaledVector(derivatives[span],3*t2-4*b+1).addScaledVector(derivatives[span+1],3*t2-2*b)
    } else {
      pos = p[span].clone().multiplyScalar(a).addScaledVector(p[span+1],b)
        .addScaledVector(second[span],(a*a*a-a)*h*h/6).addScaledVector(second[span+1],(b*b*b-b)*h*h/6)
      d = p[span+1].clone().sub(p[span]).divideScalar(h)
        .addScaledVector(second[span],(1-3*a*a)*h/6).addScaledVector(second[span+1],(3*b*b-1)*h/6)
    }
    if (d.lengthSq() < 1e-16) return null
    d.normalize()
    const i = positions.length
    if (i) arc.push(arc[i-1]+pos.distanceTo(positions[i-1]))
    frames.push(new THREE.Quaternion().setFromUnitVectors(i ? tangents[i-1] : Z.clone().applyQuaternion(basis),d)
      .multiply(i ? frames[i-1] : basis))
    positions.push(pos); tangents.push(d)
  }
  // Match the server's linearly interpolated, unwrapped roll at authored controls.
  const knotIndices = knots.map(t => times.indexOf(t)), rolls = []
  authored.forEach((q,i) => {
    if (!q) return
    const k = knotIndices[i], right = X.clone().applyQuaternion(frames[k]), desired = X.clone().applyQuaternion(q)
    let angle = Math.atan2(tangents[k].dot(right.clone().cross(desired)),right.dot(desired))
    const previous = rolls.at(-1)?.angle ?? angle
    while (angle-previous > Math.PI) angle -= 2*Math.PI
    while (angle-previous < -Math.PI) angle += 2*Math.PI
    rolls.push({at:arc[k],angle})
  })
  if (rolls.length) {
    if (rolls[0].at > 0) rolls.unshift({at:0,angle:0})
    let j = 0
    frames.forEach((q,i) => {
      while (j+1 < rolls.length && rolls[j+1].at < arc[i]) j++
      const a = rolls[j], b = rolls[j+1] ?? a
      const f = b.at > a.at ? Math.min(1,(arc[i]-a.at)/(b.at-a.at)) : 0
      q.premultiply(new THREE.Quaternion().setFromAxisAngle(tangents[i],a.angle+(b.angle-a.angle)*f))
    })
  }
  return {positions, frames, arc, pointFrames:knotIndices.map(i=>frames[i]), length:arc.at(-1)}
}

function frameAt(path, fraction) {
  const distance = fraction*path.length
  let lo = 0, hi = path.arc.length-1
  while (lo+1 < hi) { const mid = (lo+hi)>>1; if (path.arc[mid] <= distance) lo = mid; else hi = mid }
  const f = (distance-path.arc[lo])/(path.arc[hi]-path.arc[lo] || 1)
  return {position:path.positions[lo].clone().lerp(path.positions[hi],f), frame:path.frames[lo].clone().slerp(path.frames[hi],f)}
}

/** Bind a bounded cloud once, then transport it cheaply on every local update.
 * End-attached helices share a rigid end frame; terminal offsets stay in nm. */
export function bindSweepCloud(data, baseline) {
  const attached = new Map((data.edit_attachment_groups ?? []).flatMap(g=>g.helix_ids.map(id=>[id,g.end])))
  let axes = (data.helix_paths_nm ?? []).map((path,i)=>({path,id:data.helix_path_ids?.[i]}))
    .filter(a=>!data.edit_helix_ids || data.edit_helix_ids.includes(a.id))
  const stride = Math.max(1,Math.ceil(axes.length/(SWEEP_LIVE_BUDGET/2)))
  axes = axes.filter((_,i)=>i%stride===0)
  const perAxis = Math.max(2,Math.floor(SWEEP_LIVE_BUDGET/Math.max(1,axes.length))), bindings = []
  for (const {path,id} of axes) {
    // Server axes may contain only endpoints. Resample their polylines so
    // straight bundles have the same legible cloud density as curved ones.
    const axis = path.map(vector), distance = [0]
    for (let i=1;i<axis.length;i++) distance.push(distance[i-1]+axis[i].distanceTo(axis[i-1]))
    const count = path.length > 1 ? Math.min(128,perAxis) : path.length
    let span = 1
    for (let j=0;j<count;j++) {
      const at = distance.at(-1)*j/Math.max(1,count-1)
      while(span+1<axis.length && distance[span]<at)span++
      const point = axis.length===1 ? axis[0].clone() : axis[span-1].clone().lerp(axis[span],
        (at-distance[span-1])/(distance[span]-distance[span-1] || 1))
      let fraction = attached.has(id) ? (attached.get(id)==='start'?0:1) : null
      if (fraction == null) {
        let best = Infinity
        for(let i=1;i<baseline.positions.length;i++) {
          const a=baseline.positions[i-1], delta=baseline.positions[i].clone().sub(a)
          const t=THREE.MathUtils.clamp(point.clone().sub(a).dot(delta)/(delta.lengthSq() || 1),0,1)
          const distance=point.distanceToSquared(a.clone().addScaledVector(delta,t))
          if(distance<best){best=distance;fraction=(baseline.arc[i-1]+t*(baseline.arc[i]-baseline.arc[i-1]))/baseline.length}
        }
      }
      const {position,frame}=frameAt(baseline,fraction)
      bindings.push({fraction,offset:point.sub(position).applyQuaternion(frame.invert())})
    }
  }
  return bindings
}
export function moveSweepCloud(bindings, path, buffer) {
  bindings.forEach(({fraction,offset},i)=>{
    const {position,frame}=frameAt(path,fraction)
    position.add(offset.clone().applyQuaternion(frame)).toArray(buffer,i*3)
  })
}
