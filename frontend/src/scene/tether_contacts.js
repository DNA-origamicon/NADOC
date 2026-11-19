import { Vector3, Quaternion } from 'three'
import { clusterMemberFilter } from './cluster_entries.js'
const v = p => new Vector3(...p)
const q = p => new Quaternion(...p)
const PAD = .167
const EPS = .001

// Non-reentrant numeric scratch: contact evaluation invokes no callbacks.
const scratch=Array.from({length:18},()=>new Vector3())
/** Conservative flat-cylinder clearance, matching the relaxation contact model. */
export function duplexGap(a, b) {
  const [p,end,r,s,u,w,ap,aq,bp,bq,du,dv,delta,cross,temp,center,line,point]=scratch
  p.fromArray(a.p); end.fromArray(a.q); r.fromArray(b.p); s.fromArray(b.q)
  u.copy(end).sub(p); w.copy(s).sub(r)
  const lu=u.length(), lw=w.length()
  u.normalize(); w.normalize()
  ap.copy(p).addScaledVector(u,-PAD); aq.copy(end).addScaledVector(u,PAD)
  bp.copy(r).addScaledVector(w,-PAD); bq.copy(s).addScaledVector(w,PAD)
  const pointDistance=(x,y,z)=>{
    line.copy(z).sub(y); point.copy(x).sub(y)
    const length=line.lengthSq()
    return point.addScaledVector(line,length>1e-24 ? -Math.max(0,Math.min(1,point.dot(line)/length)) : 0).length()
  }
  let distance=Math.min(pointDistance(ap,bp,bq),pointDistance(aq,bp,bq),pointDistance(bp,ap,aq),pointDistance(bq,ap,aq))
  du.copy(aq).sub(ap); dv.copy(bq).sub(bp); delta.copy(ap).sub(bp)
  cross.copy(du).cross(dv)
  const den=cross.lengthSq()
  if(den>1e-12) {
    const t=temp.copy(dv).cross(delta).dot(cross)/den
    const z=temp.copy(du).cross(delta).dot(cross)/den
    if(t>=0 && t<=1 && z>=0 && z<=1) distance=delta.addScaledVector(du,t).addScaledVector(dv,-z).length()
  }
  if(lu<1e-12 || lw<1e-12) return distance-2
  center.copy(r).add(s).sub(p).sub(end).multiplyScalar(.5)
  const cosine=Math.min(1,Math.abs(u.dot(w))), radial=temp.copy(u).cross(w).length()
  return Math.max(distance-2,
    Math.abs(center.dot(u))-(lu/2+PAD)-(lw/2+PAD)*cosine-radial,
    Math.abs(center.dot(w))-(lw/2+PAD)-(lu/2+PAD)*cosine-radial)
}

/** Include every paired duplex, including geometry outside the tether network. */
export function buildContactBodies(design, geometry, pending = []) {
  const clusters = design?.cluster_transforms ?? []
  const filters = clusters.map(c => [c, clusterMemberFilter(c, design)]).reverse()
  const poses = new Map(pending.map(p => [p.clusterId, p]))
  const sites = new Map()
  for (const n of geometry ?? []) {
    if (n.is_unpaired || n.is_flexible_segment || n.copy_k) continue
    const axis = n.helical_site?.axis_point
    if (!axis) continue
    const owner = filters.find(([, f]) => f?.(n))?.[0]
    const id = owner?.id ?? `static:${n.helix_id}`
    const key = `${id}/${n.helix_id}`
    let point = v(axis)
    const pose = poses.get(id)
    if (pose && owner) {
      point.sub(v(owner.pivot)).sub(v(owner.translation)).applyQuaternion(q(owner.rotation).invert())
        .add(v(owner.pivot)).sub(v(pose.pivot)).applyQuaternion(q(pose.rotation))
        .add(v(pose.pivot)).add(v(pose.translation))
    }
    if (!sites.has(key)) sites.set(key, { owner: id, points: new Map() })
    sites.get(key).points.set(n.bp_index, point.toArray())
  }
  const bodies = []
  for (const { owner, points } of sites.values()) {
    let run = []
    const flush = () => { if (run.length) bodies.push({ owner, p: points.get(run[0]), q: points.get(run.at(-1)) }) }
    for (const bp of [...points.keys()].sort((a, b) => a - b)) {
      const last = run.at(-1)
      if (run.length && (bp !== last + 1 || v(points.get(bp)).sub(v(points.get(run[0])))
        .cross(v(points.get(last)).sub(v(points.get(run[0])))).length() > 1e-6)) {
        flush(); run = bp === last + 1 ? [last] : []
      }
      run.push(bp)
    }
    flush()
  }
  return bodies
}

const transform = (point, from, to) => v(point).sub(v(from.pos)).applyQuaternion(q(from.quat).invert())
  .applyQuaternion(q(to.quat)).add(v(to.pos)).toArray()
const interpolate = (a, b, t) => Object.fromEntries(Object.keys(a).map(id => [id, {
  pos: v(a[id].pos).lerp(v(b[id].pos), t).toArray(), quat: q(a[id].quat).slerp(q(b[id].quat), t).toArray(),
}]))

/** Bounded swept sampling, not atomistic collision detection. Existing penetrations
 * may decrease; fixed/fixed overlaps cannot block an unrelated moving body. */
export function createTetherContactGuard(bodies, initial) {
  let accepted = structuredClone(initial)
  const pairs = []
  for (let i = 0; i < bodies.length; i++) for (let j = 0; j < i; j++) {
    if (bodies[i].owner !== bodies[j].owner && (initial[bodies[i].owner] || initial[bodies[j].owner])) pairs.push([i, j])
  }
  const placed = poses => bodies.map(b => poses[b.owner] ? { ...b,
    p: transform(b.p, initial[b.owner], poses[b.owner]), q: transform(b.q, initial[b.owner], poses[b.owner]),
  } : b)
  const gap = (a, b) => {
    let separation2 = 0
    for (let k = 0; k < 3; k++) separation2 += Math.max(0,
      Math.min(...[a.p[k], a.q[k]]) - Math.max(b.p[k], b.q[k]),
      Math.min(b.p[k], b.q[k]) - Math.max(a.p[k], a.q[k])) ** 2
    return separation2 > 2.334 ** 2 ? Math.sqrt(separation2) - 2.334 : duplexGap(a, b)
  }
  let limits = pairs.map(([i, j]) => Math.min(0, gap(bodies[i], bodies[j])))
  return {
    accept(target, enabled = true, feasible = () => true) {
      if (!enabled) { accepted = structuredClone(target); return accepted }
      let travel = 0
      for (const b of bodies) if (initial[b.owner]) {
        const from = accepted[b.owner], to = target[b.owner]
        const radius = Math.max(v(b.p).distanceTo(v(initial[b.owner].pos)), v(b.q).distanceTo(v(initial[b.owner].pos))) + 1.167
        travel = Math.max(travel, v(from.pos).distanceTo(v(to.pos)) + radius * q(from.quat).angleTo(q(to.quat)))
      }
      // Cap work by limiting progress, never by increasing the sample spacing.
      const steps = Math.max(1, Math.ceil(travel / .05)), count = Math.min(steps, 400)
      const start = accepted
      for (let step = 1; step <= count; step++) {
        const candidate = interpolate(start, target, step / steps), geometry = placed(candidate)
        const gaps = pairs.map(([i, j]) => gap(geometry[i], geometry[j]))
        if (gaps.some((g, i) => g < limits[i] - EPS)) break
        if (feasible(candidate)) {
          accepted = candidate
          limits = gaps.map((g, i) => Math.min(0, Math.max(limits[i], g)))
        }
      }
      return structuredClone(accepted)
    },
  }
}
