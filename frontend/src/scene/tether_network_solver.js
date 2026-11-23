import { Vector3, Quaternion } from 'three'
import { duplexGap } from './tether_contacts.js'
import { createTetherContactIndex } from './tether_contact_index.js'
const EPS=.001, CONTACT_REACH=2.334
const axes=[new Vector3(1,0,0),new Vector3(0,1,0),new Vector3(0,0,1)]

/** Coupled rigid poses, with a pinned largest body and inverse-size mobility.
 * Working vectors and rod bounds are reused across projection passes. Only
 * fully validated poses leave the solver; no molecular geometry is rewritten. */
export function createTetherNetworkSolver({bodies,rods,edges,driver,fixed}, {now=()=>performance.now(),budgetMs=60}={}) {
  const ids=Object.keys(bodies), index=new Map(ids.map((id,i)=>[id,i]))
  const centers=ids.map(id=>new Vector3(...bodies[id].center))
  const weights=ids.map(id=>id===fixed?0:1/Math.max(1,bodies[id].size))
  const angular=ids.map((id,i)=>weights[i]/Math.max(1,bodies[id].radius**2))
  const driverIndex=index.get(driver)
  const clone=poses=>poses.map(p=>({pos:p.pos.clone(),quat:p.quat.clone()}))
  let accepted=centers.map(pos=>({pos:pos.clone(),quat:new Quaternion()})), passes=0, work=null
  const local=(point,i)=>new Vector3(...point).sub(i==null?new Vector3():centers[i])
  const primitives=rods.map(r=>{const owner=index.get(r.owner);return {owner,p:local(r.p,owner),q:local(r.q,owner)}})
  const links=edges.map(e=>{
    const a=index.get(e.a),b=index.get(e.b)
    return {a,b,pa:local(e.pa,a),pb:local(e.pb,b),limit:Math.max(e.contour,new Vector3(...e.pa).distanceTo(new Vector3(...e.pb))-EPS)}
  })
  const geometry=rods.map(()=>({p:[0,0,0],q:[0,0,0],lo:[0,0,0],hi:[0,0,0]}))
  const scratch=new Vector3(), aPoint=new Vector3(),bPoint=new Vector3(),normal=new Vector3()
  const ta=new Vector3(),tb=new Vector3(),ra=new Vector3(),rb=new Vector3(),rotation=new Vector3(),deltaQ=new Quaternion()
  const world=(point,owner,poses,out)=>{
    out.copy(point)
    if(owner!=null) out.applyQuaternion(poses[owner].quat).add(poses[owner].pos)
    return out
  }
  function place(i,poses,out=geometry[i]) {
    const r=primitives[i]
    world(r.p,r.owner,poses,scratch).toArray(out.p)
    world(r.q,r.owner,poses,scratch).toArray(out.q)
    for(let c=0;c<3;c++){out.lo[c]=Math.min(out.p[c],out.q[c]);out.hi[c]=Math.max(out.p[c],out.q[c])}
    return out
  }
  function placeAll(poses){for(let i=0;i<primitives.length;i++)place(i,poses)}
  const pairs=[]
  for(let i=0;i<rods.length;i++)for(let j=0;j<i;j++)
    if(rods[i].owner!==rods[j].owner && (weights[primitives[i].owner] || weights[primitives[j].owner])) pairs.push([i,j])
  // Expanded axis boxes are a conservative broad phase for the flat cylinders.
  const separated=(a,b)=>{
    let d2=0
    for(let c=0;c<3;c++){
      const d=Math.max(0,a.lo[c]-b.hi[c],b.lo[c]-a.hi[c]);d2+=d*d
      if(d2>CONTACT_REACH*CONTACT_REACH)return true
    }
    return false
  }
  placeAll(accepted)
  const gaps=pairs.map(([i,j])=>separated(geometry[i],geometry[j])?0:Math.min(0,duplexGap(geometry[i],geometry[j])+EPS))
  const contactCandidates=createTetherContactIndex(geometry,pairs,CONTACT_REACH)
  const ownerRods=ids.map((_,owner)=>primitives.flatMap((r,i)=>r.owner===owner?[i]:[]))
  function apply(pose,t,r,w,aw,lambda){
    pose.pos.addScaledVector(t,w*lambda)
    rotation.copy(r).multiplyScalar(aw*lambda)
    const angle=rotation.length()
    if(angle>1e-12)pose.quat.premultiply(deltaQ.setFromAxisAngle(rotation.multiplyScalar(1/angle),Math.min(.15,angle))).normalize()
  }
  function project(poses,a,b,value){
    const wa=weights[a]??0,wb=weights[b]??0,aa=angular[a]??0,ab=angular[b]??0
    const denom=wa*ta.lengthSq()+wb*tb.lengthSq()+aa*ra.lengthSq()+ab*rb.lengthSq()
    if(denom<1e-16)return
    const lambda=.85*value/denom
    if(wa)apply(poses[a],ta,ra,wa,aa,lambda)
    if(wb)apply(poses[b],tb,rb,wb,ab,lambda)
  }
  function tetherPass(poses){
    for(const e of links){
      world(e.pa,e.a,poses,aPoint);world(e.pb,e.b,poses,bPoint)
      normal.copy(aPoint).sub(bPoint)
      const distance=normal.length(),error=distance-e.limit
      if(error<EPS*.1 || distance<1e-12)continue
      normal.multiplyScalar(1/distance)
      ta.copy(normal).negate();tb.copy(normal)
      ra.copy(aPoint).sub(poses[e.a].pos).cross(normal).negate()
      rb.copy(bPoint).sub(poses[e.b].pos).cross(normal)
      project(poses,e.a,e.b,error)
    }
  }
  const probe={p:[0,0,0],q:[0,0,0],lo:[0,0,0],hi:[0,0,0]}, savedQ=new Quaternion(),probeQ=new Quaternion()
  function gradient(poses,i,j,current,t,r){
    t.set(0,0,0);r.set(0,0,0)
    const owner=primitives[i].owner
    if(!weights[owner])return
    const pose=poses[owner],radius=Math.max(1,bodies[ids[owner]].radius)
    savedQ.copy(pose.quat)
    for(let c=0;c<6;c++){
      const h=c<3?1e-4:1e-4/radius
      const old=c<3?pose.pos.getComponent(c):0
      if(c<3)pose.pos.setComponent(c,old+h)
      else pose.quat.copy(savedQ).premultiply(probeQ.setFromAxisAngle(axes[c-3],h))
      place(i,poses,probe)
      const derivative=(duplexGap(probe,geometry[j])-current)/h
      if(c<3){t.setComponent(c,derivative);pose.pos.setComponent(c,old)}
      else {r.setComponent(c-3,derivative);pose.quat.copy(savedQ)}
    }
  }
  function contactPass(poses){
    placeAll(poses)
    for(const k of contactCandidates()){
      const [i,j]=pairs[k],a=geometry[i],b=geometry[j]
      if(separated(a,b))continue
      const current=duplexGap(a,b),error=gaps[k]-current
      if(error<EPS*.1)continue
      gradient(poses,i,j,current,ta,ra);gradient(poses,j,i,current,tb,rb)
      const oa=primitives[i].owner,ob=primitives[j].owner
      project(poses,oa,ob,error)
      if(weights[oa])for(const n of ownerRods[oa])place(n,poses)
      if(weights[ob])for(const n of ownerRods[ob])place(n,poses)
    }
  }
  function residual(poses,contacts){
    let tether=0,penetration=0
    for(const e of links){
      world(e.pa,e.a,poses,aPoint);world(e.pb,e.b,poses,bPoint)
      tether=Math.max(tether,aPoint.distanceTo(bPoint)-e.limit)
    }
    if(contacts){
      placeAll(poses)
      for(const k of contactCandidates()){
        const [i,j]=pairs[k]
        if(!separated(geometry[i],geometry[j]))penetration=Math.max(penetration,gaps[k]-duplexGap(geometry[i],geometry[j]))
      }
    }
    return {tether,penetration}
  }
  const exportResult=contacts=>({poses:Object.fromEntries(ids.map((id,i)=>[id,{pos:accepted[i].pos.toArray(),quat:accepted[i].quat.toArray()}])),...residual(accepted,contacts)})
  function advance(target,contacts,deadline){
    work??={previous:accepted,target,contacts,attempt:0,iteration:0,poses:null}
    while(work.attempt<7 && passes>0 && now()<deadline){
      if(!work.poses){
        work.poses=clone(work.previous)
        work.poses[driverIndex].pos.lerp(work.target.pos,2**-work.attempt)
        work.poses[driverIndex].quat.slerp(work.target.quat,2**-work.attempt)
      }
      for(let pass=0;pass<5;pass++)tetherPass(work.poses)
      if(contacts)contactPass(work.poses)
      work.iteration++;passes--
      if(work.iteration%5===0){
        const result=residual(work.poses,contacts)
        if(result.tether<=EPS && result.penetration<=EPS){accepted=work.poses;work=null;return}
      }
      if(work.iteration===120){work.attempt++;work.iteration=0;work.poses=null}
    }
    if(work?.attempt===7)work=null
  }
  return {
    solve(target,contacts=true,frameBudget=budgetMs){
      passes=600
      const deadline=now()+frameBudget
      if(driver===fixed)return exportResult(contacts)
      const desired={pos:new Vector3(...target.pos),quat:new Quaternion(...target.quat)}
      const radius=bodies[driver].radius
      const distance=(p,q)=>p.pos.distanceTo(q.pos)+radius*p.quat.angleTo(q.quat)
      const length=distance(accepted[driverIndex],desired)
      if(!Number.isFinite(length))return exportResult(contacts)
      // Continue an unfinished projection across frames, but discard it on
      // reversal or contact-mode changes. Unvalidated poses never reach display.
      if(work && (work.contacts!==contacts || distance(work.target,desired)>length+1e-6))work=null
      const steps=Math.min(200,Math.max(1,Math.ceil(length/.25)))
      for(let i=0;i<steps && passes>0 && now()<deadline;i++){
        const current=accepted[driverIndex],remaining=distance(current,desired),fraction=remaining?Math.min(1,.25/remaining):1
        advance({pos:current.pos.clone().lerp(desired.pos,fraction),quat:current.quat.clone().slerp(desired.quat,fraction)},contacts,deadline)
        if(distance(current,accepted[driverIndex])<1e-8)break
      }
      return exportResult(contacts)
    },
    report(poses,contacts=true){return residual(ids.map(id=>({pos:new Vector3(...poses[id].pos),quat:new Quaternion(...poses[id].quat)})),contacts)},
  }
}
