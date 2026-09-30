/** Playback-only skinning of an exact surface. Four nearby nucleotide frames drive
 * each vertex. Connectivity stays fixed; paused/exported surfaces are rebuilt exactly.
 * This preserves small-scale surface detail without running meshing on every tick.
 */
function poses(frame, count) {
  if (!frame || !count) return null
  const stride = frame.length / count
  if (![6, 9, 12].includes(stride)) return null
  const out = new Float64Array(count * 12)
  for (let n = 0; n < count; n++) {
    const i = n * stride, o = n * 12
    out.set(frame.slice(i, i + 3), o)
    let x = frame[i + 3], y = frame[i + 4], z = frame[i + 5]
    let len = Math.hypot(x, y, z)
    if (!len) { x = 1; y = z = 0; len = 1 }
    x /= len; y /= len; z /= len
    let u = stride >= 9 ? frame[i + 6] : 0
    let v = stride >= 9 ? frame[i + 7] : 0
    let w = stride >= 9 ? frame[i + 8] : 1
    let dot = x*u + y*v + z*w
    u -= dot*x; v -= dot*y; w -= dot*z
    len = Math.hypot(u,v,w)
    if (len < 1e-8 || !Number.isFinite(len)) {
      u = Math.abs(x) < .8 ? 1 : 0; v = Math.abs(x) < .8 ? 0 : 1; w = 0
      dot = x*u + y*v; u -= dot*x; v -= dot*y; w -= dot*z
      len = Math.hypot(u,v,w)
    }
    u /= len; v /= len; w /= len
    out.set([x,y,z, v*z-w*y,w*x-u*z,u*y-v*x, u,v,w], o+3)
  }
  return out
}

export function bindSurfaceMotion(mesh, keys, reference) {
  const count = keys.length, rest = poses(reference, count)
  if (!rest || !mesh?.vertices?.length) return null
  const vertices = mesh.vertices, n = vertices.length / 3
  const ids = new Int32Array(n * 4), weights = new Float32Array(n * 4)
  const local = new Float32Array(n * 12), out = new Float32Array(vertices.length)
  const candidates = keys.map((key,i) => key[0] === '__gold__' ? -1 : i).filter(i=>i>=0)
  if (!candidates.length) return null
  // Preserve independent strand shells when the surface carries atom identity.
  const strandForKey = new Map()
  const st = mesh.vertex_strand_index_table, si = mesh.vertex_strand_index
  const nt = mesh.vertex_nuc_index_table, ni = mesh.vertex_nuc_index
  if(st && si && nt && ni) for(let j=0;j<n;j++) strandForKey.set(nt[ni[j]],st[si[j]])
  const byStrand = new Map()
  for(const k of candidates) {
    const strand=strandForKey.get(keys[k].slice(0,3).join(':'))
    if(strand == null) continue
    if(!byStrand.has(strand)) byStrand.set(strand,[])
    byStrand.get(strand).push(k)
  }
  for (let j=0;j<n;j++) {
    const near = [-1,-1,-1,-1], dist = [Infinity,Infinity,Infinity,Infinity]
    const p=j*3
    for (const k of (byStrand.get(st?.[si?.[j]]) ?? candidates)) {
      const o=k*12, dx=vertices[p]-rest[o], dy=vertices[p+1]-rest[o+1], dz=vertices[p+2]-rest[o+2]
      const d=dx*dx+dy*dy+dz*dz
      if(d>=dist[3]) continue
      let at=3
      while(at>0 && d<dist[at-1]) {dist[at]=dist[at-1];near[at]=near[at-1];at--}
      dist[at]=d;near[at]=k
    }
    let sum=0
    for(let k=0;k<4;k++) if(near[k]>=0) sum += 1 / Math.max(1e-8,dist[k]*dist[k])
    for(let k=0;k<4;k++) {
      const q=j*4+k, id=near[k];ids[q]=Math.max(0,id)
      if(id<0) continue
      weights[q]=(1/Math.max(1e-8,dist[k]*dist[k]))/sum
      const o=id*12, dx=vertices[p]-rest[o],dy=vertices[p+1]-rest[o+1],dz=vertices[p+2]-rest[o+2]
      for(let axis=0;axis<3;axis++) local[q*3+axis]=dx*rest[o+3+axis*3]+dy*rest[o+4+axis*3]+dz*rest[o+5+axis*3]
    }
  }
  return { mesh, deform(frame) {
    const current=poses(frame,count)
    if(!current) return null
    out.fill(0)
    for(let j=0;j<n;j++) for(let k=0;k<4;k++) {
      const q=j*4+k,w=weights[q],o=ids[q]*12,l=q*3,p=j*3
      if(!w) continue
      for(let axis=0;axis<3;axis++) out[p+axis] += w*(current[o+axis]+local[l]*current[o+3+axis]+local[l+1]*current[o+6+axis]+local[l+2]*current[o+9+axis])
    }
    return out
  } }
}
