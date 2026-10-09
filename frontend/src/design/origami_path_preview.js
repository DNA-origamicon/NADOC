/** Geometric helix-path preview. No scaffold/staple routing or design mutations. */
import * as THREE from 'three'

const RISE = .34
const PITCH = 2.25
const COL_PITCH = Math.sqrt(3) * PITCH / 2
const ROW_PITCH = 1.5 * PITCH
const vec = a => new THREE.Vector3(...a)
const smooth = x => { const t = Math.max(0, Math.min(1, x)); return t*t*(3-2*t) }

// Compact, even-row honeycomb footprints. Coordinates follow NADOC/caDNAno's
// row/column convention. Translating the second copy by an even-parity cell
// displacement makes a shared lattice section, rather than an arbitrary hub.
export function previewSection(hb = 6) {
  const shapes = { 6: [2,3], 12: [4,3], 18: [6,3], 24: [6,4] }
  if (!shapes[hb]) throw new Error('Preview bundles support 6, 12, 18 or 24 helices.')
  const [rows, cols] = shapes[hb]
  const cells = []
  for (let r=0;r<rows;r++) for (let c=0;c<cols;c++) cells.push({ row:r, col:c, x:c*COL_PITCH, y:r*ROW_PITCH+((r+c)%2)*PITCH/2 })
  const mx = cells.reduce((s,c)=>s+c.x,0)/hb, my = cells.reduce((s,c)=>s+c.y,0)/hb
  return { hb, cells: cells.map(c=>({...c,x:c.x-mx,y:c.y-my})),
    // Odd column shifts require an odd row shift to preserve honeycomb parity.
    splitOffset: [cols*COL_PITCH/2, (cols%2)*ROW_PITCH/2] }
}

function tangentAt(curve, u) {
  const t = curve.getUtoTmapping(u), s = 1-t
  return curve.v1.clone().sub(curve.v0).multiplyScalar(3*s*s)
    .addScaledVector(curve.v2.clone().sub(curve.v1),6*s*t)
    .addScaledVector(curve.v3.clone().sub(curve.v2),3*t*t).normalize()
}

function perpendicular(tangent, preferred) {
  let u = preferred.clone().addScaledVector(tangent,-preferred.dot(tangent))
  if (u.lengthSq()<1e-10) {
    u = new THREE.Vector3(Math.abs(tangent.x)<.8?1:0, Math.abs(tangent.x)<.8?0:1, 0)
    u.addScaledVector(tangent,-u.dot(tangent))
  }
  return u.normalize()
}

// Parallel transport avoids abrupt frame flips at inflections and in 3D. A
// distributed end rotation makes the lanes meet the same section at both ends.
function pathFrames(points, startU, endU, ts) {
  let u = perpendicular(ts[0],startU)
  const us = [u.clone()]
  for (let i=1;i<points.length;i++) {
    u.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(ts[i-1],ts[i]))
    u=perpendicular(ts[i],u); us.push(u.clone())
  }
  const last=ts.length-1, goal=perpendicular(ts[last],endU)
  const twist=Math.atan2(ts[last].dot(us[last].clone().cross(goal)),us[last].dot(goal))
  return ts.map((t,i)=>{
    const x=us[i].applyAxisAngle(t,twist*i/last)
    return {u:x,v:t.clone().cross(x).normalize()}
  })
}

export function buildOrigamiPathPreview(candidate, { hb = 6, junctionLengthNm = 7.14 } = {}) {
  const section=previewSection(hb), nodes=new Map(candidate.nodes.map(n=>[n.id,n]))
  const curves=new Map(candidate.edges.map(e=>[e.id,new THREE.CubicBezierCurve3(...e.controlPoints.map(vec))]))
  const lengths=new Map([...curves].map(([id,c])=>[id,c.getLength()]))
  const junctions=[]
  const ports=new Map()
  const warnings=[]
  for (const node of candidate.nodes.filter(n=>n.kind==='split')) {
    const incident=candidate.edges.filter(e=>e.source===node.id||e.target===node.id)
    const trunk=incident.find(e=>e.target===node.id)||incident[0]
    const children=incident.filter(e=>e!==trunk)
    if (children.length!==2) throw new Error('Origami preview requires binary shared-section splits.')
    const trunkAtStart=trunk.source===node.id, curve=curves.get(trunk.id)
    const axis=tangentAt(curve,trunkAtStart?0:1).multiplyScalar(trunkAtStart?-1:1).normalize()
    const away=e=>vec(nodes.get(e.source===node.id?e.target:e.source).position).sub(vec(node.position))
    const u=perpendicular(axis,away(children[1]).sub(away(children[0]))),v=axis.clone().cross(u).normalize()
    const offset=u.clone().multiplyScalar(section.splitOffset[0]).addScaledVector(v,section.splitOffset[1])
    const length=Math.min(junctionLengthNm,lengths.get(trunk.id)*.3)
    if(length<junctionLengthNm-.01) warnings.push('A short stem limits the shared-section length.')
    const junction={id:node.id,hb:2*hb,trunkEdgeId:trunk.id,atStart:trunkAtStart,lengthNm:length,
      position:[...node.position],u:u.toArray(),axis:axis.toArray(),offset:offset.toArray(),childEdgeIds:children.map(e=>e.id)}
    junctions.push(junction)
    ports.set(`${trunk.id}:${node.id}`,{u,offset:offset.clone().negate(),junction,trunk:true})
    children.forEach((edge,i)=>ports.set(`${edge.id}:${node.id}`,{u,offset:offset.clone().multiplyScalar(i?1:-1),junction,trunk:false}))
  }
  const paths=[],edgeSummaries=[]
  for(const edge of candidate.edges) {
    const curve=curves.get(edge.id),length=lengths.get(edge.id)
    // Uniform arc-length samples make local junction lengths independent of
    // Bezier parameterization and keep sweeps comparable across candidates.
    const steps=Math.max(32,Math.min(256,Math.ceil(length/.6)))
    const base=curve.getSpacedPoints(steps),start=ports.get(`${edge.id}:${edge.source}`),end=ports.get(`${edge.id}:${edge.target}`)
    const fallback=new THREE.Vector3(0,1,0)
    const frames=pathFrames(base,start?.u||end?.u||fallback,end?.u||start?.u||fallback,base.map((_,i)=>tangentAt(curve,i/steps)))
    const transition=Math.min(12,length*.45)
    const centerAt=(i,extra=null)=>{
      const s=length*i/steps,p=base[i].clone()
      for(const [port,d] of [[start,s],[end,length-s]]) if(port) {
        const span=port.trunk ? port.junction.lengthNm : 0
        const weight=port.trunk ? 1 : 1-smooth(d/transition)
        // A trunk occupies one half of the common section throughout its local
        // sleeve, then returns to the ordinary centerline beyond the sleeve.
        const w=port.trunk ? 1-smooth((d-span)/transition) : weight
        p.addScaledVector(port.offset,w)
        if(extra===port && d<=span+1e-6) {
          // The added block stays on the SAME moving lattice as the stem,
          // including curved sleeves. At the opposed end the tangent reverses.
          const sign=port.junction.atStart?-1:1
          p.addScaledVector(frames[i].u,2*section.splitOffset[0])
            .addScaledVector(frames[i].v,sign*2*section.splitOffset[1])
        }
      }
      return p
    }
    const addPaths=(indices,extra=null)=>{
      for(let h=0;h<hb;h++) {
        const cell=section.cells[h]
        const points=indices.map(i=>centerAt(i,extra).addScaledVector(frames[i].u,cell.x).addScaledVector(frames[i].v,cell.y).toArray())
        if(points.length<2)continue
        const contour=points.slice(1).reduce((sum,p,i)=>sum+vec(p).distanceTo(vec(points[i])),0)
        paths.push({edgeId:edge.id,helix:h,kind:extra?'junction-extension':'bundle',junctionId:extra?.junction.id||null,
          points,lengthNm:contour,estimatedNt:Math.ceil(contour/RISE),row:cell.row,col:cell.col})
      }
    }
    addPaths(Array.from({length:steps+1},(_,i)=>i))
    for(const [port,isStart] of [[start,true],[end,false]]) if(port?.trunk) {
      // Include the exact junction boundary, rounded down to the sampled path.
      const count=Math.max(1,Math.floor(port.junction.lengthNm/length*steps))
      addPaths(Array.from({length:count+1},(_,i)=>isStart?i:steps-count+i),port)
    }
    edgeSummaries.push({edgeId:edge.id,hb,lengthNm:length})
  }
  // Budget estimate is from the displayed helix contours, including local extra
  // helices. It deliberately excludes crossovers, staples and attachment paths.
  const estimatedNt=paths.reduce((s,p)=>s+p.estimatedNt,0)
  if(estimatedNt>8064)warnings.push('These helix paths exceed an 8064 nt scaffold before routing overhead.')
  return {hb,junctionHB:2*hb,junctions,paths,edges:edgeSummaries,estimatedNt,
    warnings:[...new Set(warnings)],section,routed:false}
}
