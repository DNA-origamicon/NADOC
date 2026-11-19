import { Vector3, Quaternion } from 'three'
import { clusterMemberFilter, clusterTransformSelection } from './cluster_entries.js'
import { flexAnchorKey } from './design_queries.js'
import { buildContactBodies } from './tether_contacts.js'
import { createTetherNetworkSolver } from './tether_network_solver.js'

/** Resolve the whole flexible component. Only gate-approved rigid clusters may
 * yield; geometry outside it remains an obstacle. The largest owner is pinned. */
export function buildTetherNetwork({ design, geometry, driver, pending, network, resolve }) {
  if (!network?.connections?.length || !network.gates) return null
  const component=new Set([driver])
  for (let changed=true;changed;) {
    changed=false
    for (const e of network.connections) if (component.has(e.cluster_a_id)||component.has(e.cluster_b_id)) {
      for (const id of [e.cluster_a_id,e.cluster_b_id]) if (!component.has(id)) { component.add(id); changed=true }
    }
  }
  if (component.size<3) return null
  // A follower with an unmodelled rigid connection is not free to move.
  if ([...component].some(id => !network.gates[id]?.gate)) return null
  const rods=buildContactBodies(design,geometry,pending), bodies={}
  for (const id of component) {
    const cluster=design.cluster_transforms.find(c => c.id===id)
    if (!cluster) return null
    const points=rods.filter(r => r.owner===id).flatMap(r => [r.p,r.q])
    if (!points.length) return null
    const center=points.reduce((out,p) => out.add(new Vector3(...p)),new Vector3()).multiplyScalar(1/points.length)
    const member=clusterMemberFilter(cluster,design)
    bodies[id]={ center:center.toArray(), radius:Math.max(1,...points.map(p => center.distanceTo(new Vector3(...p)))),
      size:geometry.filter(n => member?.(n)).length }
  }
  const fixed=[...component].sort((a,b) => bodies[b].size-bodies[a].size || a.localeCompare(b))[0]
  const edges=[]
  for (const e of network.connections) if (component.has(e.cluster_a_id)) {
    const keyA=flexAnchorKey(e.anchor_a,design), keyB=flexAnchorKey(e.anchor_b,design)
    if (!keyA || !keyB) return null
    const a=resolve(keyA), b=resolve(keyB)
    if (!a||!b) return null
    edges.push({ a:e.cluster_a_id,b:e.cluster_b_id,pa:a.toArray(),pb:b.toArray(),contour:e.contour_length_nm })
  }
  return { bodies, rods, edges, driver, fixed }
}

export function createCompliantTetherMotion({ store, read, pending, capture, paint, record }) {
  let enabled=true, solver=null, model=null, baselines=null, scopes=null
  return {
    setEnabled(value) { enabled=!!value },
    arm() {
      solver=null
      const s=read(), state=store.getState()
      if (s.type!=='ssdna' || s.links?.length) return false
      model=buildTetherNetwork({ design:state.currentDesign, geometry:state.currentGeometry,
        driver:s.clusterId,pending:pending(),network:s.network,resolve:s.resolve })
      if (!model || model.edges.filter(e => e.a===s.clusterId || e.b===s.clusterId).length!==s.constraints?.length) return false
      const queued=new Map(pending().map(p => [p.clusterId,p]))
      baselines=new Map(Object.keys(model.bodies).map(id => {
        const authored=state.currentDesign.cluster_transforms.find(c => c.id===id)
        return [id,{ ...authored,...queued.get(id) }]
      }))
      scopes=new Map([...baselines].map(([id,c])=>[id,clusterTransformSelection(c,state.currentDesign,state.currentGeometry)]))
      for (const [id,c] of baselines) if (id!==s.clusterId && id!==model.fixed) {
        capture?.(c.helix_ids,scopes.get(id),true)
      }
      solver=createTetherNetworkSolver(model)
      return true
    },
    solve(interactive=true) {
      if (!solver) return false
      const s=read(), center=new Vector3(...model.bodies[s.clusterId].center)
      const delta=s.dummy.quaternion.clone().multiply(s.startQuat.clone().invert())
      const target={ pos:center.clone().sub(s.startPos).applyQuaternion(delta).add(s.dummy.position).toArray(),quat:delta.toArray() }
      const result=solver.solve(target,enabled,interactive?undefined:Infinity), primary=result.poses[s.clusterId]
      s.incrQuat.fromArray(primary.quat)
      s.dummy.position.copy(s.startPos).sub(center).applyQuaternion(s.incrQuat).add(new Vector3(...primary.pos))
      s.dummy.quaternion.copy(s.incrQuat).multiply(s.startQuat)
      for (const [id,c] of baselines) if (id!==s.clusterId && id!==model.fixed) {
        const pose=result.poses[id], origin=new Vector3(...model.bodies[id].center), rotation=new Quaternion(...pose.quat)
        paint?.(c.helix_ids,origin,new Vector3(...pose.pos),rotation,scopes.get(id))
        const endPivot=new Vector3(...c.pivot).add(new Vector3(...c.translation)).sub(origin)
          .applyQuaternion(rotation).add(new Vector3(...pose.pos))
        record(id,{ pivot:[...c.pivot],translation:endPivot.sub(new Vector3(...c.pivot)).toArray(),
          rotation:rotation.multiply(new Quaternion(...c.rotation)).toArray() })
      }
      return true
    },
  }
}
